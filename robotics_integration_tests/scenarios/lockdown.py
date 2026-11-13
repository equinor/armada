"""Lockdown of one plant while another plant carries on, two robots on each."""

from typing import Dict

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import KAARSTO, IsarRobot
from robotics_integration_tests.scenarios.steps import RobotScenario
from robotics_integration_tests.utilities.flotilla_backend_api import (
    clear_emergency_state,
    get_robot_statuses,
    schedule_dummy_mission,
    send_all_robots_to_lockdown,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
    wait_for_second_task_status_of_mission_run,
    wait_until_idle_away_from_home,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 20.0
SHORT_TASK_DURATION_SECONDS = 5.0

# The robot is Available for this long after its positioning mission, which is
# the window for the test to trigger lockdown before ISAR sends the robot home.
RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS = 30

LOCKED_DOWN_PLANT = KAARSTO

LOCKDOWN_WHILE_IDLE = "LockdownWhileIdle"
LOCKDOWN_DURING_MISSION = "LockdownDuringMission"
OTHER_PLANT_WHILE_IDLE = "OtherPlantWhileIdle"
OTHER_PLANT_DURING_MISSION = "OtherPlantDuringMission"


ROSTER = [
    # A robot that is already home enters Lockdown directly, so this one is
    # sent away first.
    RobotScenario(
        name=LOCKDOWN_WHILE_IDLE,
        drives_isar_through="AwaitNextMission -> GoingToLockdown -> Lockdown",
        task_duration_in_seconds=SHORT_TASK_DURATION_SECONDS,
        return_home_delay_in_seconds=RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
    RobotScenario(
        name=LOCKDOWN_DURING_MISSION,
        drives_isar_through=(
            "Monitor -> StoppingGoToLockdown -> GoingToLockdownWithMission -> "
            "LockdownWithMission, then the mission is resumed"
        ),
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        plant=LOCKED_DOWN_PLANT,
    ),
    RobotScenario(name=OTHER_PLANT_WHILE_IDLE),
    RobotScenario(
        name=OTHER_PLANT_DURING_MISSION,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
    ),
]


def _schedule_dummy_mission(backend_url: str, robot: IsarRobot) -> Dict:
    return schedule_dummy_mission(
        backend_url=backend_url,
        robot_id=robot.robot_id,
        installation_code=robot.installation_code,
    )


def _assert_robots_are_on_two_plants(armada: Armada) -> None:
    locked_down: str = LOCKED_DOWN_PLANT.installation_code
    for name in (LOCKDOWN_WHILE_IDLE, LOCKDOWN_DURING_MISSION):
        assert armada.robots[name].installation_code == locked_down
    for name in (OTHER_PLANT_WHILE_IDLE, OTHER_PLANT_DURING_MISSION):
        assert armada.robots[name].installation_code != locked_down


def _assert_only_the_locked_down_plant_is_in_lockdown(backend_url: str) -> None:
    statuses: Dict[str, str] = get_robot_statuses(backend_url)
    assert statuses[LOCKDOWN_WHILE_IDLE] == "Lockdown", statuses
    assert statuses[LOCKDOWN_DURING_MISSION] == "Lockdown", statuses
    assert statuses[OTHER_PLANT_WHILE_IDLE] != "Lockdown", statuses
    assert statuses[OTHER_PLANT_DURING_MISSION] != "Lockdown", statuses


def lock_down_one_plant_and_verify_the_other_carries_on(armada: Armada) -> None:
    backend_url: str = armada.flotilla_backend.backend_url
    _assert_robots_are_on_two_plants(armada)

    positioning_mission: Dict = _schedule_dummy_mission(
        backend_url, armada.robots[LOCKDOWN_WHILE_IDLE]
    )
    mission_interrupted_by_lockdown: Dict = _schedule_dummy_mission(
        backend_url, armada.robots[LOCKDOWN_DURING_MISSION]
    )
    mission_running_on_other_plant: Dict = _schedule_dummy_mission(
        backend_url, armada.robots[OTHER_PLANT_DURING_MISSION]
    )

    wait_until_idle_away_from_home(
        backend_url=backend_url,
        robot_name=LOCKDOWN_WHILE_IDLE,
        mission_run_id=positioning_mission["id"],
    )
    for mission_run in (
        mission_interrupted_by_lockdown,
        mission_running_on_other_plant,
    ):
        wait_for_second_task_status_of_mission_run(
            backend_url=backend_url,
            mission_run_id=mission_run["id"],
            expected_status="InProgress",
        )

    send_all_robots_to_lockdown(
        backend_url=backend_url,
        installation_code=LOCKED_DOWN_PLANT.installation_code,
    )
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            LOCKDOWN_WHILE_IDLE: "Lockdown",
            LOCKDOWN_DURING_MISSION: "Lockdown",
        },
        timeout=240,
    )

    # A robot caught by the lockdown holds its mission until release, so these
    # can only succeed if the other plant is unaffected.
    mission_started_on_other_plant_during_lockdown: Dict = _schedule_dummy_mission(
        backend_url, armada.robots[OTHER_PLANT_WHILE_IDLE]
    )
    wait_for_all_mission_run_statuses(
        backend_url=backend_url,
        mission_run_expectations={
            mission_running_on_other_plant["id"]: "Successful",
            mission_started_on_other_plant_during_lockdown["id"]: "Successful",
        },
        timeout=240,
    )
    _assert_only_the_locked_down_plant_is_in_lockdown(backend_url)

    clear_emergency_state(
        backend_url=backend_url,
        installation_code=LOCKED_DOWN_PLANT.installation_code,
    )

    # Flotilla shows Lockdown and LockdownWithMission alike. Only the latter has
    # a mission to resume on release.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=mission_interrupted_by_lockdown["id"],
        expected_status="Successful",
        timeout=300,
    )
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={scenario.name: "Home" for scenario in ROSTER},
        timeout=300,
    )
