"""A return home superseded by a new mission, once while running and once while paused."""

from functools import partial

from robotics_integration_tests.scenarios.fleet import (
    TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    RobotScenario,
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
