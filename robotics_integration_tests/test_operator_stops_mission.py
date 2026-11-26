from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios.fleet import (
    Fleet,
    mission_is_under_way_with_tasks_left,
    robot_is,
)
from robotics_integration_tests.scenarios.stopping import (
    ROSTER,
    STOP_DURING_MISSION,
    STOP_WHILE_PAUSED,
)


def test_operator_stops_a_running_and_a_paused_mission(
    armada_with_robot_roster,
) -> None:
    """The comment on an action is the ISAR states it drives the robot through."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(STOP_DURING_MISSION, STOP_WHILE_PAUSED)

    fleet.wait_until(
        mission_is_under_way_with_tasks_left(STOP_DURING_MISSION),
        mission_is_under_way_with_tasks_left(STOP_WHILE_PAUSED),
    )
    # Monitor -> Stopping -> AwaitNextMission
    fleet.stop_mission(STOP_DURING_MISSION)
    # Monitor -> Pausing -> Paused
    fleet.pause_mission(STOP_WHILE_PAUSED)

    fleet.wait_until(robot_is(STOP_WHILE_PAUSED, "Paused"))
    # Paused -> StoppingPausedMission -> AwaitNextMission
    fleet.stop_mission(STOP_WHILE_PAUSED)

    fleet.wait_until(*fleet.expected_outcomes())
