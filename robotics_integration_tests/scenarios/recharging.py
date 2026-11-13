"""Low battery, reached by one idle robot and one robot on a mission."""

from typing import List

from robotics_integration_tests.scenarios.steps import (
    POLL_INTERVAL_IN_SECONDS,
    RobotScenario,
    Step,
    do,
    latest_mission_is,
    robot_is,
    robot_is_idle_away_from_home,
    schedule_dummy_mission,
    wait_for,
)

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

STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS = 420.0


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


def _robot_that_starts_fully_charged_and_drains_quickly(
    name: str,
    drives_isar_through: str,
    task_duration_in_seconds: float,
    mission_battery_start_threshold: float,
    battery_recharge_threshold: float,
    return_home_delay_in_seconds: int,
    steps: List[Step],
) -> RobotScenario:
    return RobotScenario(
        name=name,
        drives_isar_through=drives_isar_through,
        task_duration_in_seconds=task_duration_in_seconds,
        initial_battery_level=FULL_BATTERY,
        battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
        battery_poll_interval_in_seconds=BATTERY_POLL_INTERVAL_SECONDS,
        mission_battery_start_threshold=mission_battery_start_threshold,
        battery_recharge_threshold=battery_recharge_threshold,
        return_home_delay_in_seconds=return_home_delay_in_seconds,
        step_timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
        steps=steps,
    )


# Only reachable when the stop handed the mission back as an AbortedMission
# (equinor/isar#1176).
robot_is_recharging_with_its_mission_on_hold = robot_is("RechargingWithMission")

ROSTER = [
    _robot_that_starts_fully_charged_and_drains_quickly(
        name="LowBatteryWhileIdle",
        drives_isar_through=(
            "AwaitNextMission -> GoingToRecharging -> Recharging -> Home"
        ),
        task_duration_in_seconds=IDLE_ROBOT_TASK_DURATION_SECONDS,
        mission_battery_start_threshold=IDLE_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=IDLE_ROBOT_RECHARGE_THRESHOLD,
        return_home_delay_in_seconds=IDLE_ROBOT_RETURN_HOME_DELAY_SECONDS,
        steps=[
            do(schedule_dummy_mission),
            wait_for(robot_is_idle_away_from_home),
            wait_for(robot_is("Recharging")),
            wait_for(robot_is("Home")),
            wait_for(latest_mission_is("Successful")),
        ],
    ),
    _robot_that_starts_fully_charged_and_drains_quickly(
        name="LowBatteryDuringMission",
        drives_isar_through=(
            "Monitor -> StoppingGoToRecharge -> GoingToRechargingWithMission -> "
            "RechargingWithMission, then the mission is resumed"
        ),
        task_duration_in_seconds=MISSION_ROBOT_TASK_DURATION_SECONDS,
        mission_battery_start_threshold=MISSION_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=MISSION_ROBOT_RECHARGE_THRESHOLD,
        return_home_delay_in_seconds=MISSION_ROBOT_RETURN_HOME_DELAY_SECONDS,
        steps=[
            do(schedule_dummy_mission),
            wait_for(robot_is_recharging_with_its_mission_on_hold),
            wait_for(robot_is("Home")),
            wait_for(latest_mission_is("Successful")),
        ],
    ),
]
