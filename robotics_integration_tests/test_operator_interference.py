from typing import List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios import lockdown, maintenance, stopping
from robotics_integration_tests.scenarios.fleet import (
    Fleet,
    RobotScenario,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    robot_is,
)
from robotics_integration_tests.scenarios.lockdown import (
    LOCKDOWN_DURING_MISSION,
    LOCKDOWN_WHILE_IDLE,
    LOCKED_DOWN_PLANT,
)
from robotics_integration_tests.scenarios.maintenance import (
    MAINTENANCE_DURING_MISSION,
    MAINTENANCE_WHILE_IDLE,
    STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE,
)
from robotics_integration_tests.scenarios.stopping import (
    MISSION_WHILE_RETURN_HOME_PAUSED,
    MISSION_WHILE_RETURNING_HOME,
    STOP_DURING_MISSION,
    STOP_WHILE_PAUSED,
)

OPERATED_ROBOTS: List[RobotScenario] = [*stopping.ROSTER, *maintenance.ROSTER]
ROSTER: List[RobotScenario] = [*OPERATED_ROBOTS, *lockdown.ROSTER]


def test_operator_interference_while_another_plant_is_locked_down(
    armada_with_robot_roster,
) -> None:
    """Every action taken on a robot, in the order it is taken.

    The comment on an action is the ISAR states it drives the robot through.
    Robots acted on after the same wait are configured alike, so that they are
    in their window together.

    Lockdown is installation-wide. The robots an operator interferes with are
    on another plant than the one that is locked down, and must carry on.
    """
    armada: Armada = armada_with_robot_roster(ROSTER)
    lockdown.assert_only_the_lockdown_robots_are_on_the_locked_down_plant(
        armada, other_robots=OPERATED_ROBOTS
    )
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(
        STOP_DURING_MISSION,
        STOP_WHILE_PAUSED,
        MAINTENANCE_DURING_MISSION,
        MISSION_WHILE_RETURNING_HOME,
        MISSION_WHILE_RETURN_HOME_PAUSED,
        LOCKDOWN_WHILE_IDLE,
        LOCKDOWN_DURING_MISSION,
    )
    # Home -> Maintenance
    fleet.set_maintenance_mode(MAINTENANCE_WHILE_IDLE)

    fleet.wait_until(
        mission_is_under_way_with_tasks_left(STOP_DURING_MISSION),
        mission_is_under_way_with_tasks_left(STOP_WHILE_PAUSED),
        mission_is_under_way_with_tasks_left(MAINTENANCE_DURING_MISSION),
    )
    # Monitor -> Stopping -> AwaitNextMission
    fleet.stop_mission(STOP_DURING_MISSION)
    # Monitor -> Pausing -> Paused
    fleet.pause_mission(STOP_WHILE_PAUSED)
    # Monitor -> StoppingDueToMaintenance -> Maintenance
    fleet.set_maintenance_mode(MAINTENANCE_DURING_MISSION)

    fleet.wait_until(
        latest_mission_is(LOCKDOWN_WHILE_IDLE, "Successful"),
        robot_is(LOCKDOWN_WHILE_IDLE, "Available"),
        mission_is_under_way_with_tasks_left(LOCKDOWN_DURING_MISSION),
    )
    # Everything below, until the emergency state is cleared, happens while the
    # other plant is locked down.
    # AwaitNextMission -> GoingToLockdown -> Lockdown
    # Monitor -> StoppingGoToLockdown -> GoingToLockdownWithMission ->
    # LockdownWithMission
    fleet.send_all_robots_to_lockdown(LOCKED_DOWN_PLANT)

    fleet.wait_until(
        robot_is(STOP_WHILE_PAUSED, "Paused"),
        robot_is(MAINTENANCE_WHILE_IDLE, "Maintenance"),
        robot_is(MAINTENANCE_DURING_MISSION, "Maintenance"),
        latest_mission_is(
            MAINTENANCE_DURING_MISSION, STATUS_OF_A_MISSION_INTERRUPTED_BY_MAINTENANCE
        ),
    )
    # Paused -> StoppingPausedMission -> AwaitNextMission
    fleet.stop_mission(STOP_WHILE_PAUSED)
    # Maintenance -> UnknownStatus -> Home
    fleet.release_maintenance_mode(MAINTENANCE_WHILE_IDLE)
    fleet.release_maintenance_mode(MAINTENANCE_DURING_MISSION)

    # ISAR starts the return home itself once the return-home delay has passed
    # after the mission. A robot that is already home has nothing to return
    # from, which is why these two were given a mission first.
    fleet.wait_until(
        robot_is(MISSION_WHILE_RETURNING_HOME, "ReturningHome"),
        robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturningHome"),
    )
    # ISAR does not let an operator stop a return home. Scheduling a mission
    # supersedes it instead.
    # ReturningHome -> StoppingReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURNING_HOME)
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused
    fleet.pause_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    fleet.wait_until(robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturnHomePaused"))
    # ReturnHomePaused -> StoppingPausedReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    # A robot caught by a lockdown holds its mission until release, so the two
    # missions scheduled above can only succeed if their plant is unaffected.
    fleet.wait_until(
        *fleet.expected_outcomes(OPERATED_ROBOTS),
        robot_is(LOCKDOWN_WHILE_IDLE, "Lockdown"),
        robot_is(LOCKDOWN_DURING_MISSION, "Lockdown"),
    )
    for robot in OPERATED_ROBOTS:
        assert "Lockdown" not in fleet.statuses_seen[robot.name], (
            f"{robot.name} is on another plant than the one that was locked "
            f"down, but was seen in {fleet.statuses_seen[robot.name]}"
        )

    fleet.clear_emergency_state(LOCKED_DOWN_PLANT)

    # Flotilla shows Lockdown and LockdownWithMission alike. Only the latter
    # has a mission to resume on release.
    fleet.wait_until(*fleet.expected_outcomes(lockdown.ROSTER))
