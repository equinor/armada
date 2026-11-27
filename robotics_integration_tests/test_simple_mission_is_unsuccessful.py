from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot, RobotConfig
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_dummy_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)

ROSTER = [RobotConfig(name="Placebot", should_fail_normal_task=True)]


def test_simple_mission_with_three_tags_is_unsuccessful(
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
        expected_status="Failed",
    )

    wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot.name,
        expected_status="Home",
    )
