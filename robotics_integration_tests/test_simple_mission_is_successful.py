from typing import Dict, List, Tuple

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_until_all_expected_files_uploaded,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)
from robotics_integration_tests.utilities.mqtt_publisher import (
    publish_analysis_result,
    publish_visualization_available,
)
from robotics_integration_tests.utilities.sara_backend_api import (
    wait_for_sara_inspection_ids,
    wait_for_sara_log_count,
    wait_for_sara_logs,
)
from robotics_integration_tests.utilities.signalr_client import (
    ANALYSIS_RESULT_READY,
    INSPECTION_VISUALIZATION_READY,
    MISSION_RUN_UPDATED,
    assert_no_signalr_event,
    carries_inspection_id,
    mission_run_reached,
    wait_for_signalr_event,
)

# Logged by SARA's MQTT handler when triggering an inspection record's
# analyses throws.
SARA_ANALYSIS_TRIGGER_FAILED_LOG = (
    "Error occurred while triggering analyses for InspectionId"
)

# Keys under Analysis:Workflows in SARA's appsettings.json. SARA puts one of
# these on the wire verbatim as workflow.WorkflowType.
FENCILLA = "fencilla"
CLOE = "cloe"
THERMAL_READING = "thermal-reading"

# Long enough for Flotilla to have handled a message and for the hub to have
# delivered anything it was going to deliver. Shared by every negative
# assertion below rather than paid once each.
SIGNALR_SETTLE_SECONDS = 10


def _broker_endpoint(armada: Armada) -> Tuple[str, int]:
    return "localhost", int(
        armada.flotilla_broker.broker.get_exposed_port(settings.FLOTILLA_BROKER_PORT)
    )


def _assert_analysis_results_reach_the_frontend(
    armada: Armada, inspection_ids: List[str]
) -> None:
    """Announce analysis results the way SARA does, and check the browser is told.

    There is no Argo here, so no workflow ever completes and SARA never
    publishes a result of its own. The messages are injected onto the broker
    instead, which leaves the whole Flotilla half of the path under test:
    deserialising SARA's payload, resolving the inspection, and broadcasting on
    the hub.

    That half decides what the operator sees. The frontend never reads the
    payload's contents -- InspectionsContext.tsx treats the event purely as a
    cue to invalidate its query cache and refetch from SARA -- so if the event
    does not arrive, the analysis silently never appears, however correct the
    data in SARA is. No REST assertion can catch that.

    The ids are SARA's own, read back from its logs, so this resolves the same
    identifiers Flotilla is asked to resolve in production.
    """
    host, port = _broker_endpoint(armada)
    listener = armada.signalr_listener

    inspection_id: str = inspection_ids[0]
    # A separate inspection for the thermal case, so the pin below can be stated
    # as "nothing at all arrived for this inspection" rather than as a match on
    # the serialised analysis type. A fix that changes Flotilla's AnalysisType
    # from an enum to a string would change that spelling and quietly stop the
    # pin from ever firing.
    thermal_inspection_id: str = inspection_ids[1]
    unknown_inspection_id: str = "00000000-0000-0000-0000-000000000000"

    def publish_analysis(analysis_type: str, inspection: str = inspection_id) -> None:
        publish_analysis_result(
            broker_host=host,
            broker_port=port,
            credentials=armada.mqtt_credentials,
            inspection_ids=[inspection],
            analysis_type=analysis_type,
        )

    # The analysis types Flotilla can deserialise. JsonStringEnumConverter
    # matches case-insensitively, so these map onto AnalysisType.Fencilla and
    # AnalysisType.CLOE.
    for analysis_type in (FENCILLA, CLOE):
        publish_analysis(analysis_type)
        wait_for_signalr_event(
            listener=listener,
            label=ANALYSIS_RESULT_READY,
            predicate=carries_inspection_id(inspection_id),
            timeout=30,
        )
        logger.info(f"Analysis type '{analysis_type}' reached the hub")
        listener.clear()

    # A visualization announcement is the sibling event, and the one the mission
    # page relies on for the anonymized image. Every field on this message is
    # snake_case on both sides, so unlike the analysis result it round-trips.
    # This also guards the "Visulization" misspelling, which matches in flotilla's
    # backend and frontend today: correcting it on one side alone breaks the UI.
    publish_visualization_available(
        broker_host=host,
        broker_port=port,
        credentials=armada.mqtt_credentials,
        inspection_id=inspection_id,
    )
    wait_for_signalr_event(
        listener=listener,
        label=INSPECTION_VISUALIZATION_READY,
        predicate=carries_inspection_id(inspection_id),
        timeout=30,
    )
    listener.clear()

    # Two messages that must produce nothing, then one that must get through.
    # The last one arriving shows a payload Flotilla cannot handle does not take
    # the rest of the stream with it -- the deserialize in
    # MqttService.PublishMessageBasedOnTopic is unguarded and
    # OnSaraAnalysisResultMessage is an async void handler, so that was worth
    # establishing rather than assuming.
    publish_analysis(THERMAL_READING, inspection=thermal_inspection_id)
    publish_analysis(FENCILLA, inspection=unknown_inspection_id)
    publish_analysis(FENCILLA)

    wait_for_signalr_event(
        listener=listener,
        label=ANALYSIS_RESULT_READY,
        predicate=carries_inspection_id(inspection_id),
        timeout=30,
    )

    # Not a barrier: MqttEventHandler dispatches with a fire-and-forget
    # `_ = SignalRService.SendMessageAsync(...)`, so arrival order is not
    # guaranteed. Settle once, then check both negatives.
    assert_no_signalr_event(
        listener=listener,
        label=ANALYSIS_RESULT_READY,
        predicate=carries_inspection_id(unknown_inspection_id),
        settle_time=SIGNALR_SETTLE_SECONDS,
        message=(
            "An analysis result for an inspection Flotilla does not know "
            "reached the hub. MqttEventHandler is expected to log and drop it."
        ),
    )

    # Pins a known Flotilla bug rather than endorsing it. SARA publishes
    # analysisType as the free-form string "thermal-reading"
    # (workflow.WorkflowType), while Flotilla deserialises it into the enum
    # AnalysisType, whose member is ThermalReading. The hyphen makes the mapping
    # impossible, JsonSerializer.Deserialize throws, and the event is lost, so
    # thermal readings never appear in the UI.
    assert_no_signalr_event(
        listener=listener,
        label=ANALYSIS_RESULT_READY,
        predicate=carries_inspection_id(thermal_inspection_id),
        settle_time=0,
        message=(
            "A 'thermal-reading' analysis result reached the hub. Flotilla has "
            "presumably been fixed to accept SARA's hyphenated analysisType -- "
            "replace this pin with an assertion that the event arrives."
        ),
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

    # The REST assertion above says the backend knows the mission finished; this
    # says an operator's browser was told. The two are independent, and only the
    # second one keeps the UI current.
    wait_for_signalr_event(
        listener=armada.signalr_listener,
        label=MISSION_RUN_UPDATED,
        predicate=mission_run_reached(mission_run_id, "Successful"),
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
        expected_count=len(mission_run.get("tasks")),
    )

    # SARA has the inspections but no analysis will ever complete without Argo,
    # so announce the results itself would have published and check they reach
    # the operator.
    inspection_ids: List[str] = wait_for_sara_inspection_ids(
        container=armada.sara.container,
        expected_count=len(mission_run.get("tasks")),
    )
    _assert_analysis_results_reach_the_frontend(
        armada=armada, inspection_ids=inspection_ids
    )
