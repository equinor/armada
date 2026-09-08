from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_until_all_expected_files_uploaded,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS,
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)
from robotics_integration_tests.utilities.sara_backend_api import (
    wait_for_sara_log_count,
    wait_for_sara_logs,
)
from robotics_integration_tests.utilities import mission_status

# Logged by SARA's MQTT handler when triggering an inspection record's
# analyses throws.
SARA_ANALYSIS_TRIGGER_FAILED_LOG = (
    "Error occurred while triggering analyses for InspectionId"
)


def test_simple_mission_with_three_tags_is_successful(
    armada_with_single_successful_robot: Armada,
) -> None:
    armada: Armada = armada_with_single_successful_robot
    robot_name, robot = next(iter(armada.robots.items()))
    mission_payload: Dict = get_dummy_mission_payload_with_installation(robot.installation_code)
    mission: Dict = create_mission(backend_url=armada.flotilla_backend.backend_url, payload=mission_payload)
    mission_run: Dict = schedule_mission(
        backend_url=armada.flotilla_backend.backend_url,
        robot_id=robot.robot_id,
        mission_id=mission["id"],
    )

    mission_run_id: str = mission_run.get("id")
    logger.info(
        f"Scheduled mission {mission['id']} with id {mission_run['id']} "
        f"on robot {robot_name}"
        )

    _ = wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Successful",
    )

    wait_until_all_expected_files_uploaded(
        container_name=robot.installation_code.lower(),
        connection_string=armada.armada_storage.azurite_containers.get(
            settings.SARA_RAW_STORAGE_CONTAINER
        ).host_connection_string,
        expected_file_count=len(mission_run.get("tasks")),
    )

    _ = wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )

    # ISAR announces the mission's progress over MQTT, and Flotilla derives the
    # operator-visible mission state from it. Asserting the whole sequence rather
    # than just the final value turns any change to that protocol into a visible,
    # deliberate decision instead of a silent one.
    #
    # equinor/isar#1176 removes the leading NotStarted publish, so when that ships
    # this expectation becomes [IN_PROGRESS, SUCCESSFUL]. The failure is the point:
    # it forces the contract change to be acknowledged here.
    assert armada.mqtt_recorder.mission_status_trace(mission_run_id) == [
        mission_status.NOT_STARTED,
        mission_status.IN_PROGRESS,
        mission_status.SUCCESSFUL,
    ], (
        "Unexpected mission status sequence published by ISAR: "
        f"{armada.mqtt_recorder.mission_status_trace(mission_run_id)}"
    )

    # There is no Argo in the test environment, so submitting the analysis
    # throws and SARA logs once per inspection record that requested one.
    # SARA does not log per workflow type, so this cannot assert on the
    # anonymizer specifically.
    wait_for_sara_logs(
        container=armada.sara.container,
        log_message=SARA_ANALYSIS_TRIGGER_FAILED_LOG,
    )

    # SARA runs only the analyses a mission explicitly asks for; there is no
    # default analysis by file extension. Wait until every inspection result
    # has been ingested, then assert that only the tasks requesting an analysis
    # triggered one.
    wait_for_sara_log_count(
        container=armada.sara.container,
        log_message="Created inspection record with InspectionId",
        expected_count=len(mission_run.get("tasks")),
    )
    wait_for_sara_log_count(
        container=armada.sara.container,
        log_message=SARA_ANALYSIS_TRIGGER_FAILED_LOG,
        expected_count=DUMMY_MISSION_TASKS_REQUESTING_ANALYSIS,
    )
