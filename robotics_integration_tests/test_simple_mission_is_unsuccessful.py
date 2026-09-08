from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)
from robotics_integration_tests.utilities import mission_status


def test_simple_mission_with_three_tags_is_unsuccessful(
    armada_with_single_failing_robot: Armada,
) -> None:
    armada: Armada = armada_with_single_failing_robot
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
        f"Scheduled mission {mission['id']} with id {mission_run_id} on robot {robot_name}"
    )

    _ = wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Failed",
    )

    _ = wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )

    # A mission that fails while running is still announced as InProgress first:
    # ISAR publishes that when it dispatches the mission, before any task has had
    # a chance to fail. See the note in test_simple_mission_is_successful about
    # the dependency on equinor/isar#1176.
    assert armada.mqtt_recorder.mission_status_trace(mission_run_id) == [
        mission_status.IN_PROGRESS,
        mission_status.FAILED,
    ], (
        "Unexpected mission status sequence published by ISAR: "
        f"{armada.mqtt_recorder.mission_status_trace(mission_run_id)}"
    )
