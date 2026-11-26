from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import HULDRA, KAARSTO
from robotics_integration_tests.utilities.fleet import (
    Fleet,
    RobotScenario,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    robot_is,
)

# Lockdown is triggered once the idle robot is away from home and the other
# has tasks left. These durations make the two overlap for about 25 seconds.
SHORT_TASK_DURATION_SECONDS = 5.0
TASK_DURATION_THAT_OUTLASTS_THE_SHORT_MISSION_SECONDS = 25.0

# The robot is Available for this long after its positioning mission, which is
# the window for the test to trigger lockdown before ISAR sends the robot home.
RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS = 30

LOCKED_DOWN_PLANT = KAARSTO
OTHER_PLANT = HULDRA

LOCKDOWN_WHILE_IDLE = "LockdownWhileIdle"
LOCKDOWN_DURING_MISSION = "LockdownDuringMission"
BYSTANDER_ON_ANOTHER_PLANT = "BystanderOnAnotherPlant"

LOCKED_DOWN_ROBOTS = [
    # A robot that is already home enters Lockdown directly, so this one is
    # sent away first.
    RobotScenario(
        name=LOCKDOWN_WHILE_IDLE,
        task_duration_in_seconds=SHORT_TASK_DURATION_SECONDS,
        return_home_delay_in_seconds=RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
    RobotScenario(
        name=LOCKDOWN_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_OUTLASTS_THE_SHORT_MISSION_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
]

# Given its mission during the lockdown, which it must complete.
BYSTANDER = RobotScenario(name=BYSTANDER_ON_ANOTHER_PLANT, plant=OTHER_PLANT)

ROSTER = [*LOCKED_DOWN_ROBOTS, BYSTANDER]


def test_lockdown_of_one_plant_leaves_another_plant_alone(
    armada_with_robot_roster,
) -> None:
    """Lockdown is installation-wide. A robot on another plant than the one
    that is locked down must carry on.

    The comment on an action is the ISAR states it drives the robot through.
    """
    armada: Armada = armada_with_robot_roster(ROSTER)
    _assert_only_the_lockdown_robots_are_on_the_locked_down_plant(armada)
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


def _assert_only_the_lockdown_robots_are_on_the_locked_down_plant(
    armada: Armada,
) -> None:
    """Checked against the plant each robot registered with in Flotilla."""
    locked_down: str = LOCKED_DOWN_PLANT.installation_code
    for robot in LOCKED_DOWN_ROBOTS:
        plant: str = armada.robots[robot.name].installation_code
        assert plant == locked_down, (
            f"{robot.name} must be on the plant that is locked down, "
            f"{locked_down}, but is on {plant}"
        )
    assert armada.robots[BYSTANDER.name].installation_code != locked_down, (
        f"{BYSTANDER.name} must be on another plant than the one that is locked "
        f"down, {locked_down}"
    )
