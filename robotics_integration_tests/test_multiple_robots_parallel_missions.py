from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
)


def test_multiple_robots_with_different_outcomes(
    armada_with_multiple_robots: Armada,
) -> None:
    """Run four robots in parallel, each configured with a different
    combination of mission success/failure and return-home success/failure.

    +---------------------+------------------+---------------------+
    | Robot               | Mission outcome  | Return-home outcome |
    +---------------------+------------------+---------------------+
    | MissionOkThenHome   | Successful       | Home                |
    | MissionOkThenLost   | Successful       | InterventionNeeded  |
    | MissionFailThenHome | Failed           | Home                |
    | MissionFailThenLost | Failed           | InterventionNeeded  |
    +---------------------+------------------+---------------------+
    """
    armada: Armada = armada_with_multiple_robots
    backend_url: str = armada.flotilla_backend.backend_url

    robot_expectations = {
        "MissionOkThenHome": {
            "mission_status": "Successful",
            "robot_status": "Home",
            "expect_blobs": True,
        },
        "MissionOkThenLost": {
            "mission_status": "Successful",
            "robot_status": "InterventionNeeded",
            "expect_blobs": True,
        },
        "MissionFailThenHome": {
            "mission_status": "Failed",
            "robot_status": "Home",
            "expect_blobs": False,
        },
        "MissionFailThenLost": {
            "mission_status": "Failed",
            "robot_status": "InterventionNeeded",
            "expect_blobs": False,
        },
    }

    raw_storage_conn: str = armada.flotilla_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    # Schedule all missions — they execute in parallel on the robots.
    mission_runs: Dict[str, Dict] = {}
    for robot_name in robot_expectations:
        robot: IsarRobot = armada.robots[robot_name]
        mission_payload: Dict = get_dummy_mission_payload_with_installation(robot.installation_code)
        mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
        mission_run: Dict = schedule_mission(
            backend_url=backend_url,
            robot_id=robot.robot_id,
            mission_id=mission["id"],
        )
        mission_runs[robot_name] = mission_run
        logger.info(
            f"Scheduled mission {mission['id']} with id {mission_run['id']} "
            f"on robot {robot_name}"
        )

    wait_for_all_mission_run_statuses(
        backend_url=backend_url,
        mission_run_expectations={
            mission_runs[name]["id"]: exp["mission_status"]
            for name, exp in robot_expectations.items()
        },
    )

    # All robots share the same installation and blob container. The blob
    # folder path contains the mission run ID, so we can verify per-robot
    # blob counts: successful missions should have blobs, failed ones should not.
    blob_container_name: str = next(
        iter(armada.robots.values())
    ).installation_code.lower()

    wait_for_all_mission_blobs(
        container_name=blob_container_name,
        connection_string=raw_storage_conn,
        mission_blob_expectations={
            mission_runs[name]["id"]: len(mission_runs[name].get("tasks", []))
            if exp["expect_blobs"]
            else 0
            for name, exp in robot_expectations.items()
        },
    )

    _ = wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            name: exp["robot_status"]
            for name, exp in robot_expectations.items()
        },
    )

    receiver = armada.teams_webhook_receiver
    assert receiver is not None, "Teams webhook receiver was not started"

    wait_for_all_teams_notifications(
        receiver=receiver,
        notification_expectations={
            name: exp["robot_status"] == "InterventionNeeded"
            for name, exp in robot_expectations.items()
        },
    )
