from robotics_integration_tests.armada import Armada
from functools import partial

from robotics_integration_tests.utilities.fleet import (
    TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    Fleet,
    RobotScenario,
    robot_is,
)

PROMPT_RETURN_HOME_DELAY_SECONDS = 5

MISSION_WHILE_RETURNING_HOME = "MissionWhileReturningHome"
MISSION_WHILE_RETURN_HOME_PAUSED = "MissionWhileReturnHomePaused"

_robot_with_time_to_interfere = partial(
    RobotScenario,
    task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    return_home_delay_in_seconds=PROMPT_RETURN_HOME_DELAY_SECONDS,
)

# The mission that supersedes the return home is the one that must succeed.
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
    fleet = Fleet(armada, ROSTER)

    # ISAR starts the return home itself once the return-home delay has passed
    # after a mission. A robot that is already home has nothing to return
    # from, which is why these two are given a mission first.
    fleet.schedule_dummy_mission(
        MISSION_WHILE_RETURNING_HOME, MISSION_WHILE_RETURN_HOME_PAUSED
    )

    fleet.wait_until(
        robot_is(MISSION_WHILE_RETURNING_HOME, "ReturningHome"),
        robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturningHome"),
    )
    # ReturningHome -> StoppingReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURNING_HOME)
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused
    fleet.pause_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    fleet.wait_until(robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturnHomePaused"))
    # ReturnHomePaused -> StoppingPausedReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    fleet.wait_until(*fleet.expected_outcomes())
