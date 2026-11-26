from functools import partial
from typing import List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_interfere_with_running_mission,
)
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.failure_notes import (
    naming_the_robot_of_each_mission_run,
)
from robotics_integration_tests.utilities.fleet import (
    POLL_INTERVAL_IN_SECONDS,
    Fleet,
    RobotScenario,
    robot_has_been,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)

# --- Every combination of mission and return-home success and failure ---


def _outcome_matrix_robot(
    name: str, mission_fails: bool = False, return_home_fails: bool = False
) -> RobotScenario:
    return RobotScenario(
        name=name,
        should_fail_normal_task=mission_fails,
        should_fail_return_home=return_home_fails,
        expected_mission_status="Failed" if mission_fails else "Successful",
        expected_robot_status="InterventionNeeded" if return_home_fails else "Home",
    )


OUTCOME_MATRIX_ROBOTS: List[RobotScenario] = [
    _outcome_matrix_robot("MissionOkThenHome"),
    _outcome_matrix_robot("MissionOkThenLost", return_home_fails=True),
    _outcome_matrix_robot("MissionFailThenHome", mission_fails=True),
    _outcome_matrix_robot(
        "MissionFailThenLost", mission_fails=True, return_home_fails=True
    ),
]

# --- Low battery, reached by one idle robot and one robot on a mission ---

# isar-robot's battery model: it charges at home and discharges away from home,
# by a fixed amount per published sample.
BATTERY_PUBLISH_INTERVAL_SECONDS = 1.0
BATTERY_POLL_INTERVAL_SECONDS = 1.0
DISCHARGE_PER_SECOND = 0.4 / BATTERY_PUBLISH_INTERVAL_SECONDS
CHARGE_PER_SECOND = 2.0 / BATTERY_PUBLISH_INTERVAL_SECONDS
FULL_BATTERY = 100.0

DUMMY_MISSION_TASK_COUNT = 3
# Observed: a mission takes about this much longer than its tasks.
MISSION_START_AND_COMPLETION_SECONDS = 10.0

# Covers running low, recharging and, for the robot that was on a mission,
# running that mission again.
TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS = 600.0

LOW_BATTERY_WHILE_IDLE = "LowBatteryWhileIdle"
LOW_BATTERY_DURING_MISSION = "LowBatteryDuringMission"


def _seconds_away_from_home_until_battery_is_below(threshold: float) -> float:
    return (FULL_BATTERY - threshold) / DISCHARGE_PER_SECOND


IDLE_ROBOT_TASK_DURATION_SECONDS = 5.0
IDLE_ROBOT_MISSION_THRESHOLD = 85.0
IDLE_ROBOT_RECHARGE_THRESHOLD = 98.0
IDLE_ROBOT_RETURN_HOME_DELAY_SECONDS = 30

_idle_robot_mission_seconds = (
    DUMMY_MISSION_TASK_COUNT * IDLE_ROBOT_TASK_DURATION_SECONDS
    + MISSION_START_AND_COMPLETION_SECONDS
)
_idle_robot_runs_low_after_seconds = _seconds_away_from_home_until_battery_is_below(
    IDLE_ROBOT_MISSION_THRESHOLD
)
assert (
    _idle_robot_mission_seconds < _idle_robot_runs_low_after_seconds
), "The idle robot must run low after its mission, not during it"
assert (
    _idle_robot_runs_low_after_seconds
    < _idle_robot_mission_seconds + IDLE_ROBOT_RETURN_HOME_DELAY_SECONDS
), "The idle robot must run low before it returns home on its own and charges"
assert (
    IDLE_ROBOT_RECHARGE_THRESHOLD - IDLE_ROBOT_MISSION_THRESHOLD
) / CHARGE_PER_SECOND > 5 * POLL_INTERVAL_IN_SECONDS, (
    "Recharging must last for several polls to be observed"
)

MISSION_ROBOT_TASK_DURATION_SECONDS = 25.0
MISSION_ROBOT_MISSION_THRESHOLD = 75.0
MISSION_ROBOT_RECHARGE_THRESHOLD = 96.0
MISSION_ROBOT_RETURN_HOME_DELAY_SECONDS = 10

assert (
    _seconds_away_from_home_until_battery_is_below(MISSION_ROBOT_MISSION_THRESHOLD)
    < DUMMY_MISSION_TASK_COUNT * MISSION_ROBOT_TASK_DURATION_SECONDS
), "The mission robot must run low while its mission still has tasks left"


_robot_that_starts_fully_charged_and_drains_quickly = partial(
    RobotScenario,
    initial_battery_level=FULL_BATTERY,
    battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
    battery_poll_interval_in_seconds=BATTERY_POLL_INTERVAL_SECONDS,
)

RECHARGING_ROBOTS: List[RobotScenario] = [
    # AwaitNextMission -> GoingToRecharging -> Recharging -> Home
    _robot_that_starts_fully_charged_and_drains_quickly(
        name=LOW_BATTERY_WHILE_IDLE,
        task_duration_in_seconds=IDLE_ROBOT_TASK_DURATION_SECONDS,
        mission_battery_start_threshold=IDLE_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=IDLE_ROBOT_RECHARGE_THRESHOLD,
        return_home_delay_in_seconds=IDLE_ROBOT_RETURN_HOME_DELAY_SECONDS,
    ),
    # Monitor -> StoppingGoToRecharge -> GoingToRechargingWithMission ->
    # RechargingWithMission, then the mission is resumed
    _robot_that_starts_fully_charged_and_drains_quickly(
        name=LOW_BATTERY_DURING_MISSION,
        task_duration_in_seconds=MISSION_ROBOT_TASK_DURATION_SECONDS,
        mission_battery_start_threshold=MISSION_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=MISSION_ROBOT_RECHARGE_THRESHOLD,
        return_home_delay_in_seconds=MISSION_ROBOT_RETURN_HOME_DELAY_SECONDS,
    ),
]

ROSTER: List[RobotScenario] = [*OUTCOME_MATRIX_ROBOTS, *RECHARGING_ROBOTS]


def test_robots_play_out_their_missions_without_interference(
    armada_with_robot_roster,
) -> None:
    """Each robot is given one mission and is then left alone."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(*(robot.name for robot in ROSTER))

    # The outcomes waited for below prove these had no effect.
    for robot in ROSTER:
        assert_cannot_interfere_with_running_mission(
            armada=armada, robot=fleet.robot(robot.name)
        )

    fleet.wait_until(
        *fleet.expected_outcomes(),
        robot_has_been(LOW_BATTERY_WHILE_IDLE, "Recharging"),
        # Only reachable when the stop handed the mission back as an
        # AbortedMission (equinor/isar#1176).
        robot_has_been(LOW_BATTERY_DURING_MISSION, "RechargingWithMission"),
        timeout_in_seconds=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )

    _assert_blobs_and_notifications_of_the_outcome_matrix(fleet)


def _assert_blobs_and_notifications_of_the_outcome_matrix(fleet: Fleet) -> None:
    armada = fleet.armada
    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    def expected_blob_count(robot: RobotScenario) -> int:
        if robot.should_fail_normal_task:
            return 0
        return len(fleet.mission_runs[robot.name][0].get("tasks", []))

    # The blob folder path contains the mission run ID, so blobs can be counted
    # per robot although every robot uploads to the same container.
    with naming_the_robot_of_each_mission_run(
        {
            fleet.mission_runs[robot.name][0]["id"]: robot.name
            for robot in OUTCOME_MATRIX_ROBOTS
        }
    ):
        wait_for_all_mission_blobs(
            container_name=OUTCOME_MATRIX_ROBOTS[0].plant.installation_code.lower(),
            connection_string=raw_storage_conn,
            mission_blob_expectations={
                fleet.mission_runs[robot.name][0]["id"]: expected_blob_count(robot)
                for robot in OUTCOME_MATRIX_ROBOTS
            },
        )

    receiver = armada.teams_webhook_receiver
    assert receiver is not None, "Teams webhook receiver was not started"

    wait_for_all_teams_notifications(
        receiver=receiver,
        notification_expectations={
            robot.name: robot.should_fail_return_home for robot in OUTCOME_MATRIX_ROBOTS
        },
    )
