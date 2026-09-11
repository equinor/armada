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
from robotics_integration_tests.utilities.signalr_client import (
    MISSION_RUN_UPDATED,
    mission_run_reached,
    wait_for_signalr_event,
)


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

    # A failure is the case an operator most needs to see without reloading, so
    # assert the hub carried it and not just that the database recorded it.
    wait_for_signalr_event(
        listener=armada.signalr_listener,
        label=MISSION_RUN_UPDATED,
        predicate=mission_run_reached(mission_run_id, "Failed"),
    )

    _ = wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )
