"""Low battery, reached by one idle robot and one robot on a mission."""

from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.scenarios.steps import (
    POLL_INTERVAL_IN_SECONDS,
    Step,
    immediately,
    mission_status,
    robot_is_idle_away_from_home,
    robot_status,
    schedule_dummy_mission,
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

assert (
    _seconds_away_from_home_until_battery_is_below(MISSION_ROBOT_MISSION_THRESHOLD)
    < DUMMY_MISSION_TASK_COUNT * MISSION_ROBOT_TASK_DURATION_SECONDS
), "The mission robot must run low while its mission still has tasks left"


ROSTER = [
    # AwaitNextMission -> GoingToRecharging -> Recharging -> Home
    RobotScenario(
        name="LowBatteryWhileIdle",
        alias="isar_low_battery_while_idle",
        task_duration_in_seconds=IDLE_ROBOT_TASK_DURATION_SECONDS,
        battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
        battery_poll_interval_in_seconds=BATTERY_POLL_INTERVAL_SECONDS,
        mission_battery_start_threshold=IDLE_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=IDLE_ROBOT_RECHARGE_THRESHOLD,
        return_home_delay_in_seconds=IDLE_ROBOT_RETURN_HOME_DELAY_SECONDS,
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            Step(
                robot_is_idle_away_from_home,
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
            Step(
                robot_status("Recharging"),
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
            Step(
                robot_status("Home"),
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
            Step(mission_status("Successful")),
        ],
    ),
    # Monitor -> StoppingGoToRecharge -> GoingToRechargingWithMission ->
    # RechargingWithMission, then the mission is resumed
    RobotScenario(
        name="LowBatteryDuringMission",
        alias="isar_low_battery_during_mission",
        task_duration_in_seconds=MISSION_ROBOT_TASK_DURATION_SECONDS,
        initial_battery_level=FULL_BATTERY,
        battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
        battery_poll_interval_in_seconds=BATTERY_POLL_INTERVAL_SECONDS,
        mission_battery_start_threshold=MISSION_ROBOT_MISSION_THRESHOLD,
        battery_recharge_threshold=MISSION_ROBOT_RECHARGE_THRESHOLD,
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            # Only reachable when the stop handed the mission back as an
            # AbortedMission (equinor/isar#1176).
            Step(
                robot_status("RechargingWithMission"),
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
            Step(
                robot_status("Home"),
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
            Step(
                mission_status("Successful"),
                timeout_in_seconds=STEP_TIMEOUT_WHILE_BATTERY_RUNS_DOWN_SECONDS,
            ),
        ],
    ),
]
