"""Constraints Flotilla applies before a mission is allowed to run.

The inspection area is the main gate on whether anything happens at all: a
robot only runs missions belonging to the area it is currently in. That rule is
enforced in two separate places, and neither had coverage.

The mission queue is the other untested piece here. A robot runs one mission at
a time; anything else waits, and starts when the robot reports itself ready.
"""

from typing import Dict, List

from loguru import logger
from requests import Response

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.utilities.flotilla_backend_api import (
    add_inspection_area_to_database,
    create_mission,
    far_area_polygon,
    get_dummy_mission_payload_in_far_area,
    get_dummy_mission_payload_with_installation,
    get_inspection_areas_for_installation,
    get_mission_run_by_id,
    get_robot_by_name,
    schedule_mission,
    try_schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)


def test_scheduling_a_mission_in_another_inspection_area_is_rejected(
    armada_with_single_successful_robot: Armada,
) -> None:
    """A robot must not be sent a mission belonging to an area it is not in.

    Flotilla checks this when the mission is scheduled and answers 400. The
    rejection matters: the robot has no way to reach the tasks, so accepting
    the mission would strand it or drive it somewhere unintended.
    """
    armada: Armada = armada_with_single_successful_robot
    robot_name, robot = next(iter(armada.robots.items()))
    backend_url: str = armada.flotilla_backend.backend_url

    # Give the installation a second area, disjoint from the one the robot is in.
    add_inspection_area_to_database(
        backend_url=backend_url,
        installation_code=robot.installation_code,
        plant_code=robot.installation_code,
        name="Far Area",
        polygon=far_area_polygon,
    )

    areas: List[Dict] = get_inspection_areas_for_installation(
        backend_url=backend_url, installation_code=robot.installation_code
    )
    assert len(areas) >= 2, f"Expected a second inspection area, got {areas}"

    robot_state: Dict = get_robot_by_name(backend_url=backend_url, name=robot_name)
    robot_area_id: str = robot_state["currentInspectionAreaId"]

    mission: Dict = create_mission(
        backend_url=backend_url,
        payload=get_dummy_mission_payload_in_far_area(robot.installation_code),
    )

    # The mission must have landed in the other area, or the test proves nothing.
    far_area_id: str = mission["inspectionArea"]["id"]
    assert far_area_id != robot_area_id, (
        f"Mission was placed in the robot's own inspection area ({robot_area_id}), "
        f"so this would not exercise the mismatch check"
    )
    logger.info(
        f"Robot is in area {robot_area_id}, mission was placed in area {far_area_id}"
    )

    response: Response = try_schedule_mission(
        backend_url=backend_url,
        robot_id=robot.robot_id,
        mission_id=mission["id"],
    )

    assert response.status_code == 400, (
        f"Expected 400 for a mission in another inspection area, "
        f"got {response.status_code}: {response.text}"
    )


def test_two_missions_for_one_robot_run_one_after_the_other(
    armada_with_single_successful_robot: Armada,
) -> None:
    """A robot runs one mission at a time; the second waits in the queue.

    Flotilla starts the next queued run when the robot reports a status that
    can accept missions. Nothing tested the queue at all, so a regression that
    ran both at once, or never started the second, would have gone unnoticed.
    """
    armada: Armada = armada_with_single_successful_robot
    robot_name, robot = next(iter(armada.robots.items()))
    backend_url: str = armada.flotilla_backend.backend_url

    mission: Dict = create_mission(
        backend_url=backend_url,
        payload=get_dummy_mission_payload_with_installation(robot.installation_code),
    )

    first_run: Dict = schedule_mission(
        backend_url=backend_url, robot_id=robot.robot_id, mission_id=mission["id"]
    )
    second_run: Dict = schedule_mission(
        backend_url=backend_url, robot_id=robot.robot_id, mission_id=mission["id"]
    )
    logger.info(f"Queued runs {first_run['id']} then {second_run['id']} on {robot_name}")

    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=first_run["id"],
        expected_status="Ongoing",
    )

    # While the first is running the second must not have started.
    second: Dict = get_mission_run_by_id(
        backend_url=backend_url, mission_run_id=second_run["id"]
    )
    assert second["status"] == "Queued", (
        f"Second run should still be Queued while the first is Ongoing, "
        f"got {second['status']}"
    )

    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=first_run["id"],
        expected_status="Successful",
    )
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=second_run["id"],
        expected_status="Successful",
    )

    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )
