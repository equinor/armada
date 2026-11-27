from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot, RobotConfig
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_until_all_expected_files_uploaded,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_dummy_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)
from robotics_integration_tests.utilities.sara_backend_api import (
    wait_for_sara_log_count,
    wait_for_sara_logs,
)

# Logged by SARA's MQTT handler when triggering an inspection record's
# analyses throws.
SARA_ANALYSIS_TRIGGER_FAILED_LOG = (
    "Error occurred while triggering analyses for InspectionId"
)

ROSTER = [RobotConfig(name="Placebot")]


def test_simple_mission_with_three_tags_is_successful(
    armada_with_robot_roster,
) -> None:
    armada: Armada = armada_with_robot_roster(ROSTER)
    robot: IsarRobot = armada.robots[ROSTER[0].name]
    mission_run: Dict = schedule_dummy_mission(
        armada.flotilla_backend.backend_url, robot
    )

    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run["id"],
        expected_status="Successful",
    )

    wait_until_all_expected_files_uploaded(
        container_name=robot.installation_code.lower(),
        connection_string=armada.armada_storage.azurite_containers.get(
            settings.SARA_RAW_STORAGE_CONTAINER
        ).host_connection_string,
        expected_file_count=len(mission_run.get("tasks")),
    )

    wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot.name,
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
