from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    HULDRA,
    KAARSTO,
    IsarRobot,
    RobotConfig,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    clear_emergency_state,
    is_robot_status,
    schedule_dummy_mission,
    send_all_robots_to_lockdown,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
    wait_for_robot_status,
    wait_for_second_task_status_of_mission_run,
)

TIMEOUT_SECONDS = 240

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
    RobotConfig(
        name=LOCKDOWN_WHILE_IDLE,
        task_duration_in_seconds=SHORT_TASK_DURATION_SECONDS,
        return_home_delay_in_seconds=RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
    RobotConfig(
        name=LOCKDOWN_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_OUTLASTS_THE_SHORT_MISSION_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
]

# Given its mission during the lockdown, which it must complete.
BYSTANDER = RobotConfig(name=BYSTANDER_ON_ANOTHER_PLANT, plant=OTHER_PLANT)

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
    backend_url: str = armada.flotilla_backend.backend_url
    idle: IsarRobot = armada.robots[LOCKDOWN_WHILE_IDLE]
    on_mission: IsarRobot = armada.robots[LOCKDOWN_DURING_MISSION]
    bystander: IsarRobot = armada.robots[BYSTANDER_ON_ANOTHER_PLANT]

    idle_run: Dict = schedule_dummy_mission(
        backend_url, idle.robot_id, idle.installation_code
    )
    interrupted_run: Dict = schedule_dummy_mission(
        backend_url, on_mission.robot_id, on_mission.installation_code
    )

    wait_for_mission_run_status(
        backend_url, idle_run["id"], "Successful", timeout=TIMEOUT_SECONDS
    )
    wait_for_robot_status(
        backend_url, LOCKDOWN_WHILE_IDLE, "Available", timeout=TIMEOUT_SECONDS
    )
    wait_for_second_task_status_of_mission_run(
        backend_url, interrupted_run["id"], "InProgress", timeout=TIMEOUT_SECONDS
    )
    # AwaitNextMission -> GoingToLockdown -> Lockdown
    # Monitor -> StoppingGoToLockdown -> GoingToLockdownWithMission ->
    # LockdownWithMission
    send_all_robots_to_lockdown(backend_url, LOCKED_DOWN_PLANT.installation_code)
    # A robot caught by a lockdown holds its mission until release, so this
    # mission can only succeed if the bystander's plant is unaffected.
    bystander_run: Dict = schedule_dummy_mission(
        backend_url, bystander.robot_id, bystander.installation_code
    )

    wait_for_all_robot_statuses(
        backend_url,
        {LOCKDOWN_WHILE_IDLE: "Lockdown", LOCKDOWN_DURING_MISSION: "Lockdown"},
        timeout=TIMEOUT_SECONDS,
    )
    wait_for_mission_run_status(
        backend_url, bystander_run["id"], "Successful", timeout=TIMEOUT_SECONDS
    )
    wait_for_robot_status(
        backend_url, BYSTANDER_ON_ANOTHER_PLANT, "Home", timeout=TIMEOUT_SECONDS
    )
    for robot in LOCKED_DOWN_ROBOTS:
        assert is_robot_status(backend_url, robot.name, "Lockdown"), (
            f"{robot.name} must still be in Lockdown when "
            f"{BYSTANDER_ON_ANOTHER_PLANT} has completed its mission"
        )

    clear_emergency_state(backend_url, LOCKED_DOWN_PLANT.installation_code)

    # Flotilla shows Lockdown and LockdownWithMission alike. Only the latter
    # has a mission to resume on release.
    wait_for_all_mission_run_statuses(
        backend_url,
        {idle_run["id"]: "Successful", interrupted_run["id"]: "Successful"},
        timeout=TIMEOUT_SECONDS,
    )
    wait_for_all_robot_statuses(
        backend_url,
        {LOCKDOWN_WHILE_IDLE: "Home", LOCKDOWN_DURING_MISSION: "Home"},
        timeout=TIMEOUT_SECONDS,
    )


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
