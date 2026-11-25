"""Maintenance mode, entered by one idle robot and one robot on a mission."""

from robotics_integration_tests.scenarios.fleet import (
    TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    RobotScenario,
)

MAINTENANCE_WHILE_IDLE = "MaintenanceWhileIdle"
MAINTENANCE_DURING_MISSION = "MaintenanceDuringMission"

# ISAR announces the interrupted mission on its mission_aborted topic, so
# Flotilla records it as Aborted rather than Cancelled. It is abandoned rather
# than resumed when the robot is released.
STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE = "Aborted"

ROSTER = [
    RobotScenario(name=MAINTENANCE_WHILE_IDLE, expected_mission_status=None),
    RobotScenario(
        name=MAINTENANCE_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        expected_mission_status=STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE,
    ),
]
