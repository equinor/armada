from functools import partial
from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    RobotConfig,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_interfere_with_running_mission,
)
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_dummy_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)

# --- Every combination of mission and return-home success and failure ---


def _outcome_matrix_robot(
    name: str, mission_fails: bool = False, return_home_fails: bool = False
) -> RobotConfig:
    return RobotConfig(
        name=name,
        should_fail_normal_task=mission_fails,
        should_fail_return_home=return_home_fails,
    )


def _expected_mission_status(robot: RobotConfig) -> str:
    return "Failed" if robot.should_fail_normal_task else "Successful"


def _expected_robot_status(robot: RobotConfig) -> str:
    return "InterventionNeeded" if robot.should_fail_return_home else "Home"


OUTCOME_MATRIX_ROBOTS: List[RobotConfig] = [
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
# The waits in flotilla_backend_api sleep this long between polls.
POLL_INTERVAL_IN_SECONDS = 1.0
DISCHARGE_PER_SECOND = 0.4 / BATTERY_PUBLISH_INTERVAL_SECONDS
CHARGE_PER_SECOND = 2.0 / BATTERY_PUBLISH_INTERVAL_SECONDS
FULL_BATTERY = 100.0

DUMMY_MISSION_TASK_COUNT = 3
# Observed: a mission takes about this much longer than its tasks.
MISSION_START_AND_COMPLETION_SECONDS = 10.0

# Covers running low, recharging and, for the robot that was on a mission,
# running that mission again.
TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS = 600

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
    RobotConfig,
    initial_battery_level=FULL_BATTERY,
    battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
    battery_poll_interval_in_seconds=BATTERY_POLL_INTERVAL_SECONDS,
)

RECHARGING_ROBOTS: List[RobotConfig] = [
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

ROSTER: List[RobotConfig] = [*OUTCOME_MATRIX_ROBOTS, *RECHARGING_ROBOTS]


def test_robots_play_out_their_missions_without_interference(
    armada_with_robot_roster,
) -> None:
    """Each robot is given one mission and is then left alone."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url

    mission_runs: Dict[str, Dict] = {
        robot.name: schedule_dummy_mission(
            backend_url,
            armada.robots[robot.name].robot_id,
            armada.robots[robot.name].installation_code,
        )
        for robot in ROSTER
    }

    # The outcomes waited for below prove these had no effect.
    for robot in ROSTER:
        assert_cannot_interfere_with_running_mission(
            armada=armada, robot=armada.robots[robot.name]
        )

    wait_for_all_robot_statuses(
        backend_url,
        {
            LOW_BATTERY_WHILE_IDLE: "Recharging",
            # Only reachable when the stop handed the mission back as an
            # AbortedMission (equinor/isar#1176).
            LOW_BATTERY_DURING_MISSION: "RechargingWithMission",
        },
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )
    wait_for_all_mission_run_statuses(
        backend_url,
        {
            mission_runs[robot.name]["id"]: _expected_mission_status(robot)
            for robot in ROSTER
        },
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )
    wait_for_all_robot_statuses(
        backend_url,
        {robot.name: _expected_robot_status(robot) for robot in ROSTER},
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )

    _assert_blobs_and_notifications_of_the_outcome_matrix(armada, mission_runs)


def _assert_blobs_and_notifications_of_the_outcome_matrix(
    armada: Armada, mission_runs: Dict[str, Dict]
) -> None:
    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    def expected_blob_count(robot: RobotConfig) -> int:
        if robot.should_fail_normal_task:
            return 0
        return len(mission_runs[robot.name].get("tasks", []))

    # The blob folder path contains the mission run ID, so blobs can be counted
    # per robot although every robot uploads to the same container.
    wait_for_all_mission_blobs(
        container_name=OUTCOME_MATRIX_ROBOTS[0].plant.installation_code.lower(),
        connection_string=raw_storage_conn,
        mission_blob_expectations={
            mission_runs[robot.name]["id"]: expected_blob_count(robot)
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
