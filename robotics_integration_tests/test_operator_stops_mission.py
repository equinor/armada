from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    IsarRobot,
    RobotConfig,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    pause_mission,
    schedule_dummy_mission,
    stop_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
    wait_for_robot_status,
    wait_for_second_task_status_of_mission_run,
)

# Both robots are acted on in the same window, so they share this.
TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 15.0
TIMEOUT_SECONDS = 240

STOP_DURING_MISSION = "StopDuringMission"
STOP_WHILE_PAUSED = "StopWhilePaused"

ROSTER = [
    RobotConfig(
        name=STOP_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    ),
    RobotConfig(
        name=STOP_WHILE_PAUSED,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    ),
]


def test_operator_stops_a_running_and_a_paused_mission(
    armada_with_robot_roster,
) -> None:
    """The comment on an action is the ISAR states it drives the robot through."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url
    running: IsarRobot = armada.robots[STOP_DURING_MISSION]
    paused: IsarRobot = armada.robots[STOP_WHILE_PAUSED]

    running_run: Dict = schedule_dummy_mission(
        backend_url, running.robot_id, running.installation_code
    )
    paused_run: Dict = schedule_dummy_mission(
        backend_url, paused.robot_id, paused.installation_code
    )

    for mission_run in (running_run, paused_run):
        wait_for_second_task_status_of_mission_run(
            backend_url, mission_run["id"], "InProgress", timeout=TIMEOUT_SECONDS
        )
    # Monitor -> Stopping -> AwaitNextMission
    stop_mission(backend_url, running.robot_id)
    # Monitor -> Pausing -> Paused
    pause_mission(backend_url, paused.robot_id)

    wait_for_robot_status(
        backend_url, STOP_WHILE_PAUSED, "Paused", timeout=TIMEOUT_SECONDS
    )
    # Paused -> StoppingPausedMission -> AwaitNextMission
    stop_mission(backend_url, paused.robot_id)

    wait_for_all_mission_run_statuses(
        backend_url,
        {running_run["id"]: "Cancelled", paused_run["id"]: "Cancelled"},
        timeout=TIMEOUT_SECONDS,
    )
    wait_for_all_robot_statuses(
        backend_url,
        {STOP_DURING_MISSION: "Home", STOP_WHILE_PAUSED: "Home"},
        timeout=TIMEOUT_SECONDS,
    )
