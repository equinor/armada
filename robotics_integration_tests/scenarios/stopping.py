"""A mission stopped by an operator, once while running and once while paused."""

from robotics_integration_tests.scenarios.fleet import (
    TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    RobotScenario,
)

STOP_DURING_MISSION = "StopDuringMission"
STOP_WHILE_PAUSED = "StopWhilePaused"

ROSTER = [
    RobotScenario(
        name=STOP_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        expected_mission_status="Cancelled",
    ),
    RobotScenario(
        name=STOP_WHILE_PAUSED,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        expected_mission_status="Cancelled",
    ),
]
