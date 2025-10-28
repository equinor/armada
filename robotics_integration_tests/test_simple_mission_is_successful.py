from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_until_all_expected_files_uploaded,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_echo_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)


def test_simple_mission_with_three_tags_is_successful(
    armada_with_single_successful_robot: Armada,
) -> None:
    armada: Armada = armada_with_single_successful_robot
    robot_name, robot = next(iter(armada.robots.items()))
    echo_mission_id: str = "986"

    mission_run: Dict = schedule_echo_mission(
        backend_url=armada.flotilla_backend.backend_url,
        robot_id=robot.robot_id,
        mission_id=echo_mission_id,
        installation_code=robot.installation_code,
    )

    mission_run_id: str = mission_run.get("id")
    logger.info(
        f"Scheduled echo mission {echo_mission_id} with id {mission_run_id} on robot {robot_name}"
    )

    _ = wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Successful",
    )

    wait_until_all_expected_files_uploaded(
        container_name=robot.installation_code.lower(),
        connection_string=armada.flotilla_storage.azurite_containers.get(
            settings.SARA_RAW_STORAGE_CONTAINER
        ).host_connection_string,
        expected_file_count=len(mission_run.get("tasks")),
    )

    _ = wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )
