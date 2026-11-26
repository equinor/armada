from robotics_integration_tests.armada import Armada
from robotics_integration_tests.utilities.fleet import (
    TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    Fleet,
    RobotScenario,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    robot_is,
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


def test_maintenance_mode_while_idle_and_during_mission(
    armada_with_robot_roster,
) -> None:
    """The comment on an action is the ISAR states it drives the robot through."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(MAINTENANCE_DURING_MISSION)
    # Home -> Maintenance
    fleet.set_maintenance_mode(MAINTENANCE_WHILE_IDLE)

    fleet.wait_until(mission_is_under_way_with_tasks_left(MAINTENANCE_DURING_MISSION))
    # Monitor -> StoppingDueToMaintenance -> Maintenance
    fleet.set_maintenance_mode(MAINTENANCE_DURING_MISSION)

    fleet.wait_until(
        robot_is(MAINTENANCE_WHILE_IDLE, "Maintenance"),
        robot_is(MAINTENANCE_DURING_MISSION, "Maintenance"),
        latest_mission_is(
            MAINTENANCE_DURING_MISSION, STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE
        ),
    )
    # Maintenance -> UnknownStatus -> Home
    fleet.release_maintenance_mode(MAINTENANCE_WHILE_IDLE)
    fleet.release_maintenance_mode(MAINTENANCE_DURING_MISSION)

    fleet.wait_until(*fleet.expected_outcomes())
