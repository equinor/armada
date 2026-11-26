from functools import partial
from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    IsarRobot,
    robot_for_multi_robot_test,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    pause_mission,
    schedule_dummy_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
    wait_for_robot_status,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 15.0
PROMPT_RETURN_HOME_DELAY_SECONDS = 5
TIMEOUT_SECONDS = 240

MISSION_WHILE_RETURNING_HOME = "MissionWhileReturningHome"
MISSION_WHILE_RETURN_HOME_PAUSED = "MissionWhileReturnHomePaused"

# Both robots are acted on in the same window, so they share these.
_robot_with_time_to_interfere = partial(
    robot_for_multi_robot_test,
    task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    return_home_delay_in_seconds=PROMPT_RETURN_HOME_DELAY_SECONDS,
)

ROSTER = [
    _robot_with_time_to_interfere(name=MISSION_WHILE_RETURNING_HOME),
    _robot_with_time_to_interfere(name=MISSION_WHILE_RETURN_HOME_PAUSED),
]


def test_new_mission_supersedes_a_running_and_a_paused_return_home(
    armada_with_robot_roster,
) -> None:
    """ISAR does not let an operator stop a return home. A new mission
    supersedes it instead.

    The comment on an action is the ISAR states it drives the robot through.
    """
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url
    returning: IsarRobot = armada.robots[MISSION_WHILE_RETURNING_HOME]
    paused: IsarRobot = armada.robots[MISSION_WHILE_RETURN_HOME_PAUSED]

    # ISAR starts the return home itself once the return-home delay has passed
    # after a mission. A robot that is already home has nothing to return
    # from, which is why these two are given a mission first.
    for robot in (returning, paused):
        schedule_dummy_mission(backend_url, robot.robot_id, robot.installation_code)

    wait_for_all_robot_statuses(
        backend_url,
        {
            MISSION_WHILE_RETURNING_HOME: "ReturningHome",
            MISSION_WHILE_RETURN_HOME_PAUSED: "ReturningHome",
        },
        timeout=TIMEOUT_SECONDS,
    )
    # ReturningHome -> StoppingReturnHome -> Monitor
    superseding_run: Dict = schedule_dummy_mission(
        backend_url, returning.robot_id, returning.installation_code
    )
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused
    pause_mission(backend_url, paused.robot_id)

    wait_for_robot_status(
        backend_url,
        MISSION_WHILE_RETURN_HOME_PAUSED,
        "ReturnHomePaused",
        timeout=TIMEOUT_SECONDS,
    )
    # ReturnHomePaused -> StoppingPausedReturnHome -> Monitor
    superseding_run_after_pause: Dict = schedule_dummy_mission(
        backend_url, paused.robot_id, paused.installation_code
    )

    # The mission that supersedes the return home is the one that must succeed.
    wait_for_all_mission_run_statuses(
        backend_url,
        {
            superseding_run["id"]: "Successful",
            superseding_run_after_pause["id"]: "Successful",
        },
        timeout=TIMEOUT_SECONDS,
    )
    wait_for_all_robot_statuses(
        backend_url,
        {
            MISSION_WHILE_RETURNING_HOME: "Home",
            MISSION_WHILE_RETURN_HOME_PAUSED: "Home",
        },
        timeout=TIMEOUT_SECONDS,
    )
