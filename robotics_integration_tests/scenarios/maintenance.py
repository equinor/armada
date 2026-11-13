"""Maintenance mode, entered by one idle robot and one robot on a mission."""

from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.scenarios.steps import (
    Step,
    immediately,
    mission_is_under_way_with_tasks_left,
    mission_status,
    release_maintenance_mode,
    robot_status,
    schedule_dummy_mission,
    set_maintenance_mode,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 20.0

ROSTER = [
    # Home -> Maintenance, then UnknownStatus -> Home on release
    RobotScenario(
        name="MaintenanceWhileIdle",
        alias="isar_maintenance_while_idle",
        steps=[
            Step(immediately, then=set_maintenance_mode),
            Step(robot_status("Maintenance"), then=release_maintenance_mode),
            Step(robot_status("Home")),
        ],
    ),
    # Monitor -> StoppingDueToMaintenance -> Maintenance
    RobotScenario(
        name="MaintenanceDuringMission",
        alias="isar_maintenance_during_mission",
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            Step(mission_is_under_way_with_tasks_left, then=set_maintenance_mode),
            Step(robot_status("Maintenance")),
            # A mission interrupted by maintenance is abandoned rather than
            # resumed. ISAR announces this on its mission_aborted topic, so
            # Flotilla records it as Aborted rather than Cancelled.
            Step(mission_status("Aborted"), then=release_maintenance_mode),
            Step(robot_status("Home")),
        ],
    ),
]
