"""Maintenance mode, entered by one idle robot and one robot on a mission."""

from robotics_integration_tests.scenarios.steps import (
    RobotScenario,
    do,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    release_maintenance_mode,
    robot_is,
    schedule_dummy_mission,
    set_maintenance_mode,
    wait_for,
    when,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 20.0

# ISAR announces the interrupted mission on its mission_aborted topic, so
# Flotilla records it as Aborted rather than Cancelled.
interrupted_mission_is_abandoned_rather_than_resumed = latest_mission_is("Aborted")

ROSTER = [
    RobotScenario(
        name="MaintenanceWhileIdle",
        drives_isar_through="Home -> Maintenance, then UnknownStatus -> Home on release",
        steps=[
            do(set_maintenance_mode),
            when(robot_is("Maintenance"), release_maintenance_mode),
            wait_for(robot_is("Home")),
        ],
    ),
    RobotScenario(
        name="MaintenanceDuringMission",
        drives_isar_through="Monitor -> StoppingDueToMaintenance -> Maintenance",
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        steps=[
            do(schedule_dummy_mission),
            when(mission_is_under_way_with_tasks_left, set_maintenance_mode),
            wait_for(robot_is("Maintenance")),
            when(
                interrupted_mission_is_abandoned_rather_than_resumed,
                release_maintenance_mode,
            ),
            wait_for(robot_is("Home")),
        ],
    ),
]
