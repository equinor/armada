from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios import lockdown
from robotics_integration_tests.scenarios.fleet import (
    Fleet,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    robot_is,
)
from robotics_integration_tests.scenarios.lockdown import (
    BYSTANDER,
    BYSTANDER_ON_ANOTHER_PLANT,
    LOCKDOWN_DURING_MISSION,
    LOCKDOWN_WHILE_IDLE,
    LOCKED_DOWN_PLANT,
    LOCKED_DOWN_ROBOTS,
    ROSTER,
)


def test_lockdown_of_one_plant_leaves_another_plant_alone(
    armada_with_robot_roster,
) -> None:
    """Lockdown is installation-wide. A robot on another plant than the one
    that is locked down must carry on.

    The comment on an action is the ISAR states it drives the robot through.
    """
    armada: Armada = armada_with_robot_roster(ROSTER)
    lockdown.assert_only_the_lockdown_robots_are_on_the_locked_down_plant(armada)
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(LOCKDOWN_WHILE_IDLE, LOCKDOWN_DURING_MISSION)

    fleet.wait_until(
        latest_mission_is(LOCKDOWN_WHILE_IDLE, "Successful"),
        robot_is(LOCKDOWN_WHILE_IDLE, "Available"),
        mission_is_under_way_with_tasks_left(LOCKDOWN_DURING_MISSION),
    )
    # AwaitNextMission -> GoingToLockdown -> Lockdown
    # Monitor -> StoppingGoToLockdown -> GoingToLockdownWithMission ->
    # LockdownWithMission
    fleet.send_all_robots_to_lockdown(LOCKED_DOWN_PLANT)
    # A robot caught by a lockdown holds its mission until release, so this
    # mission can only succeed if the bystander's plant is unaffected.
    fleet.schedule_dummy_mission(BYSTANDER_ON_ANOTHER_PLANT)

    fleet.wait_until(
        *fleet.expected_outcomes([BYSTANDER]),
        robot_is(LOCKDOWN_WHILE_IDLE, "Lockdown"),
        robot_is(LOCKDOWN_DURING_MISSION, "Lockdown"),
    )
    assert "Lockdown" not in fleet.statuses_seen[BYSTANDER_ON_ANOTHER_PLANT], (
        f"{BYSTANDER_ON_ANOTHER_PLANT} is on another plant than the one that "
        f"was locked down, but was seen in "
        f"{fleet.statuses_seen[BYSTANDER_ON_ANOTHER_PLANT]}"
    )

    fleet.clear_emergency_state(LOCKED_DOWN_PLANT)

    # Flotilla shows Lockdown and LockdownWithMission alike. Only the latter
    # has a mission to resume on release.
    fleet.wait_until(*fleet.expected_outcomes(LOCKED_DOWN_ROBOTS))
