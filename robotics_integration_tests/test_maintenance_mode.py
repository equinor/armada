from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    IsarRobot,
    RobotConfig,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    is_mission_run_status,
    release_maintenance_mode,
    schedule_dummy_mission,
    set_maintenance_mode,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
    wait_for_second_task_status_of_mission_run,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 15.0
TIMEOUT_SECONDS = 240

MAINTENANCE_WHILE_IDLE = "MaintenanceWhileIdle"
MAINTENANCE_DURING_MISSION = "MaintenanceDuringMission"

# ISAR announces the interrupted mission on its mission_aborted topic, so
# Flotilla records it as Aborted rather than Cancelled. It is abandoned rather
# than resumed when the robot is released.
STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE = "Aborted"

ROSTER = [
    RobotConfig(name=MAINTENANCE_WHILE_IDLE),
    RobotConfig(
        name=MAINTENANCE_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    ),
]


def test_maintenance_mode_while_idle_and_during_mission(
    armada_with_robot_roster,
) -> None:
    """The comment on an action is the ISAR states it drives the robot through."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url
    idle: IsarRobot = armada.robots[MAINTENANCE_WHILE_IDLE]
    on_mission: IsarRobot = armada.robots[MAINTENANCE_DURING_MISSION]

    mission_run: Dict = schedule_dummy_mission(backend_url, on_mission)
    # Home -> Maintenance
    set_maintenance_mode(backend_url, idle.robot_id)

    wait_for_second_task_status_of_mission_run(
        backend_url, mission_run["id"], "InProgress", timeout=TIMEOUT_SECONDS
    )
    # Monitor -> StoppingDueToMaintenance -> Maintenance
    set_maintenance_mode(backend_url, on_mission.robot_id)

    wait_for_all_robot_statuses(
        backend_url,
        {
            MAINTENANCE_WHILE_IDLE: "Maintenance",
            MAINTENANCE_DURING_MISSION: "Maintenance",
        },
        timeout=TIMEOUT_SECONDS,
    )
    wait_for_mission_run_status(
        backend_url,
        mission_run["id"],
        STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE,
        timeout=TIMEOUT_SECONDS,
    )
    # Maintenance -> UnknownStatus -> Home
    release_maintenance_mode(backend_url, idle.robot_id)
    release_maintenance_mode(backend_url, on_mission.robot_id)

    wait_for_all_robot_statuses(
        backend_url,
        {MAINTENANCE_WHILE_IDLE: "Home", MAINTENANCE_DURING_MISSION: "Home"},
        timeout=TIMEOUT_SECONDS,
    )
    assert is_mission_run_status(
        backend_url, mission_run["id"], STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE
    ), "The interrupted mission must not be resumed when the robot is released"
