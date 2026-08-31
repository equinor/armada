"""Analysis pipeline tests: what SARA does after an inspection is ingested.

Everything here depends on the Argo stub (``custom_containers/argo_stub.py``),
which stands in for the Argo event sources in front of the analyzers. It accepts
SARA's trigger, writes the output blob, and drives the three callbacks SARA
expects back. That is enough to exercise step ordering, blob chaining, gate
skipping and failure cascades without running a single analyzer.

The mission itself is the ordinary three-task dummy mission, two of whose tasks
request an analysis. Flotilla maps the requested type onto a SARA analysis key,
and SARA expands that into a workflow chain.
"""

from typing import Dict, List

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.utilities.flotilla_backend_api import (
    DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS,
    SARA_WORKFLOW_CHAINS,
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
)
from robotics_integration_tests.utilities.sara_backend_api import (
    get_workflows_in_order,
    retry_workflow,
    wait_for_analysis_run_status,
    wait_for_inspection_records_for_mission,
    wait_for_visualization_location_status,
)

FENCILLA_CHAIN: List[str] = SARA_WORKFLOW_CHAINS["fencilla"]


def _run_dummy_mission(armada: Armada, analysis_type: str = "Fencilla") -> Dict:
    """Schedule the dummy mission and wait for it to succeed.

    Returns the mission run, whose id is also the ``flotillaMissionId`` on the
    inspection records SARA creates.
    """
    robot_name, robot = next(iter(armada.robots.items()))
    backend_url: str = armada.flotilla_backend.backend_url

    mission_payload: Dict = get_dummy_mission_payload_with_installation(
        robot.installation_code, analysis_type=analysis_type
    )
    mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
    mission_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(
        f"Scheduled mission {mission['id']} as run {mission_run['id']} on {robot_name}"
    )

    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=mission_run["id"],
        expected_status="Successful",
    )
    return mission_run


def _analysed_inspection_ids(armada: Armada, mission_run: Dict) -> List[str]:
    """Inspection ids for the mission's tasks that requested an analysis."""
    records = wait_for_inspection_records_for_mission(
        sara_url=armada.sara.backend_url,
        mission_run_id=mission_run["id"],
        expected_count=len(mission_run["tasks"]),
    )
    analysed = [record for record in records if record.get("analyses")]
    assert len(analysed) == DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS, (
        f"Expected {DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS} of "
        f"{len(records)} inspection records to have an analysis, "
        f"got {len(analysed)}"
    )
    return [record["inspectionId"] for record in analysed]


def test_fencilla_chain_runs_every_step_and_chains_the_blobs(
    armada_with_single_successful_robot: Armada,
) -> None:
    """The three-step fencilla chain runs in order, each step feeding the next.

    Asserts the ordering, that every step succeeded, that each step's input is
    the previous step's output, that the anonymizer wrote to the anonymized
    account and the final step to the visualized account, and that the
    visualization becomes available.
    """
    armada: Armada = armada_with_single_successful_robot
    mission_run: Dict = _run_dummy_mission(armada)
    inspection_ids: List[str] = _analysed_inspection_ids(armada, mission_run)

    for inspection_id in inspection_ids:
        run: Dict = wait_for_analysis_run_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            analysis_type="fencilla",
            expected_status="Succeeded",
        )

        workflows: List[Dict] = get_workflows_in_order(run)
        assert [w["workflowType"] for w in workflows] == FENCILLA_CHAIN
        assert all(w["status"] == "Succeeded" for w in workflows), (
            f"Not every workflow succeeded: "
            f"{[(w['workflowType'], w['status']) for w in workflows]}"
        )

        # The stub reports back the output location SARA gave it, so a
        # populated result is proof the callbacks completed, not just the
        # trigger.
        assert all(w["resultJson"] for w in workflows)

    # The anonymizer is what produces the visualization for this chain.
    for inspection_id in inspection_ids:
        wait_for_visualization_location_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            expected_status_code=200,
        )

    # Two analysed tasks, three steps each.
    triggered: List[str] = armada.argo_stub.get_triggered_workflow_types()
    assert triggered.count("anonymizer") == DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS
    assert triggered.count("fencilla") == DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS


def test_rain_gate_skips_the_downstream_fencilla_workflow(
    armada_with_single_successful_robot: Armada,
) -> None:
    """rain-drop is a gate: when it reports rain, fencilla must not run.

    Fence detection is unreliable in rain, so the gate exists to suppress it.
    The chain is skipped rather than failed, and the run records why.
    """
    armada: Armada = armada_with_single_successful_robot
    armada.argo_stub.set_behaviour({"rain-drop": {"result": {"rain": True}}})

    mission_run: Dict = _run_dummy_mission(armada)
    inspection_ids: List[str] = _analysed_inspection_ids(armada, mission_run)

    for inspection_id in inspection_ids:
        run: Dict = wait_for_analysis_run_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            analysis_type="fencilla",
            expected_status="Skipped",
        )
        assert run.get("skipReason"), "A skipped run must record why it was skipped"

        by_type: Dict[str, Dict] = {
            w["workflowType"]: w for w in get_workflows_in_order(run)
        }
        assert by_type["anonymizer"]["status"] == "Succeeded"
        assert by_type["rain-drop"]["status"] == "Succeeded"
        assert by_type["fencilla"]["status"] == "Skipped"

    # The gate must stop the chain before the analyzer is ever asked to run.
    assert "fencilla" not in armada.argo_stub.get_triggered_workflow_types()


def test_unparseable_gate_result_skips_the_chain(
    armada_with_single_successful_robot: Armada,
) -> None:
    """A gate that cannot be read must fail closed.

    If SARA cannot tell whether it was raining, it skips fencilla as a
    precaution rather than running it on a possibly rain-obscured image.
    """
    armada: Armada = armada_with_single_successful_robot
    armada.argo_stub.set_behaviour({"rain-drop": {"raw_result": "not valid json {{{"}})

    mission_run: Dict = _run_dummy_mission(armada)
    inspection_ids: List[str] = _analysed_inspection_ids(armada, mission_run)

    for inspection_id in inspection_ids:
        run: Dict = wait_for_analysis_run_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            analysis_type="fencilla",
            expected_status="Skipped",
        )
        assert run.get("skipReason")

    assert "fencilla" not in armada.argo_stub.get_triggered_workflow_types()


def test_trigger_failure_fails_the_analysis_run_but_not_the_mission(
    armada_with_single_successful_robot: Armada,
) -> None:
    """Argo being unavailable must not take the mission down with it.

    The analysis run fails and the failure is recorded on the workflow, but the
    mission itself is already complete and its inspection data is already
    safely in blob storage. A retry then recovers the run.
    """
    armada: Armada = armada_with_single_successful_robot
    armada.argo_stub.set_behaviour({"anonymizer": {"trigger_status": 500}})

    mission_run: Dict = _run_dummy_mission(armada)
    # The mission succeeded despite the analysis backend being down; that is the
    # point of the assertion above in _run_dummy_mission.
    inspection_ids: List[str] = _analysed_inspection_ids(armada, mission_run)

    failed_workflow_ids: List[str] = []
    for inspection_id in inspection_ids:
        run: Dict = wait_for_analysis_run_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            analysis_type="fencilla",
            expected_status="Failed",
        )
        anonymizer: Dict = get_workflows_in_order(run)[0]
        assert anonymizer["workflowType"] == "anonymizer"
        assert anonymizer["status"] == "Failed"
        assert anonymizer["errorMessage"], "A failed workflow must record an error"
        failed_workflow_ids.append(anonymizer["id"])

        # The chain must not have advanced past the step that failed.
        assert all(
            w["status"] != "Succeeded" for w in get_workflows_in_order(run)[1:]
        )

    # Recover: let the stub accept triggers again and retry the failed step.
    armada.argo_stub.set_behaviour({"anonymizer": {"trigger_status": 200}})
    for workflow_id in failed_workflow_ids:
        retry_workflow(sara_url=armada.sara.backend_url, workflow_id=workflow_id)

    for inspection_id in inspection_ids:
        run = wait_for_analysis_run_status(
            sara_url=armada.sara.backend_url,
            inspection_id=inspection_id,
            analysis_type="fencilla",
            expected_status="Succeeded",
        )
        assert [w["workflowType"] for w in get_workflows_in_order(run)] == FENCILLA_CHAIN
        assert all(w["status"] == "Succeeded" for w in get_workflows_in_order(run))
