from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot, RobotConfig
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_pause_mission,
)
from robotics_integration_tests.utilities.blob_storage import (
    wait_until_all_expected_files_uploaded,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    pause_mission,
    resume_mission,
    get_mission_run_by_id,
    schedule_dummy_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
    wait_for_second_task_status_of_mission_run,
)

ROSTER = [RobotConfig(name="Placebot")]


def test_simple_mission_pausing_and_resuming_successfully(
    armada_with_robot_roster,
) -> None:
    armada: Armada = armada_with_robot_roster(ROSTER)
    robot: IsarRobot = armada.robots[ROSTER[0].name]
    mission_run: Dict = schedule_dummy_mission(
        armada.flotilla_backend.backend_url, robot
    )
    mission_run_id: str = mission_run["id"]

    wait_for_second_task_status_of_mission_run(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="InProgress",
    )

    assert_cannot_pause_mission(armada=armada, robot=robot)

    # Assert "not Paused" rather than "is Ongoing" to avoid racing normal mission
    # progress; the property under test is that the rejected calls had no effect.
    status_after_unauthorised_attempts: str = get_mission_run_by_id(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
    ).get("status")
    assert (
        status_after_unauthorised_attempts != "Paused"
    ), f"An unauthorised caller managed to pause the mission run {mission_run_id}"

    pause_mission(
        backend_url=armada.flotilla_backend.backend_url, robot_id=robot.robot_id
    )
    logger.info(f"Paused mission run {mission_run_id} on robot {robot.name}")

    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Paused",
    )

    resume_mission(
        backend_url=armada.flotilla_backend.backend_url, robot_id=robot.robot_id
    )
    logger.info(f"Resumed mission run {mission_run_id} on robot {robot.name}")

    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Ongoing",
    )

    wait_for_mission_run_status(
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

    wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot.name,
        expected_status="Home",
    )
