from functools import partial
from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    RobotConfig,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_dummy_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
)

# isar-robot's battery model: it charges at home and discharges away from home,
# by a fixed amount per published sample.
BATTERY_PUBLISH_INTERVAL_SECONDS = 1.0
DISCHARGE_PER_SECOND = 0.4 / BATTERY_PUBLISH_INTERVAL_SECONDS
CHARGE_PER_SECOND = 2.0 / BATTERY_PUBLISH_INTERVAL_SECONDS
FULL_BATTERY = 100.0

DUMMY_MISSION_TASK_COUNT = 3
# Observed: a mission takes about this much longer than its tasks.
MISSION_START_AND_COMPLETION_SECONDS = 17.0

# Covers running low, recharging and, for the robot that was on a mission,
# running that mission again.
TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS = 600

_robot_that_starts_fully_charged_and_drains_quickly = partial(
    RobotConfig,
    initial_battery_level=FULL_BATTERY,
    battery_publish_interval_in_seconds=BATTERY_PUBLISH_INTERVAL_SECONDS,
    battery_poll_interval_in_seconds=1.0,
)

# AwaitNextMission -> GoingToRecharging -> Recharging -> Home
LOW_BATTERY_WHILE_IDLE = _robot_that_starts_fully_charged_and_drains_quickly(
    name="LowBatteryWhileIdle",
    task_duration_in_seconds=5.0,
    mission_battery_start_threshold=85.0,
    battery_recharge_threshold=98.0,
    return_home_delay_in_seconds=30,
)
# Monitor -> StoppingGoToRecharge -> GoingToRechargingWithMission ->
# RechargingWithMission, then the mission is resumed
LOW_BATTERY_DURING_MISSION = _robot_that_starts_fully_charged_and_drains_quickly(
    name="LowBatteryDuringMission",
    task_duration_in_seconds=25.0,
    mission_battery_start_threshold=75.0,
    battery_recharge_threshold=96.0,
)

ROSTER: List[RobotConfig] = [LOW_BATTERY_WHILE_IDLE, LOW_BATTERY_DURING_MISSION]


def _seconds_away_from_home_until_battery_runs_low(robot: RobotConfig) -> float:
    return (FULL_BATTERY - robot.mission_battery_start_threshold) / DISCHARGE_PER_SECOND


def _assert_the_batteries_run_low_at_the_intended_time() -> None:
    idle, on_mission = LOW_BATTERY_WHILE_IDLE, LOW_BATTERY_DURING_MISSION

    idle_mission_seconds: float = (
        DUMMY_MISSION_TASK_COUNT * idle.task_duration_in_seconds
        + MISSION_START_AND_COMPLETION_SECONDS
    )
    idle_runs_low_after_seconds: float = _seconds_away_from_home_until_battery_runs_low(
        idle
    )
    assert (
        idle_mission_seconds < idle_runs_low_after_seconds
    ), "The idle robot must run low after its mission, not during it"
    assert (
        idle_runs_low_after_seconds
        < idle_mission_seconds + idle.return_home_delay_in_seconds
    ), "The idle robot must run low before it returns home on its own and charges"

    # The waits in flotilla_backend_api poll once a second.
    seconds_spent_recharging: float = (
        idle.battery_recharge_threshold - idle.mission_battery_start_threshold
    ) / CHARGE_PER_SECOND
    assert (
        seconds_spent_recharging > 5
    ), "Recharging must last for several polls to be observed"

    assert (
        _seconds_away_from_home_until_battery_runs_low(on_mission)
        < DUMMY_MISSION_TASK_COUNT * on_mission.task_duration_in_seconds
    ), "The mission robot must run low while its mission still has tasks left"


# Checked on import, so that a change to the robots above that breaks the
# timing fails at once rather than as a timeout.
_assert_the_batteries_run_low_at_the_intended_time()


def test_low_battery_while_idle_and_during_mission(
    armada_with_robot_roster,
) -> None:
    """Each robot is given one mission and reaches recharging through its
    battery thresholds."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url

    mission_runs: Dict[str, Dict] = {
        robot.name: schedule_dummy_mission(backend_url, armada.robots[robot.name])
        for robot in ROSTER
    }

    wait_for_all_robot_statuses(
        backend_url,
        {
            LOW_BATTERY_WHILE_IDLE.name: "Recharging",
            # Only reachable when the stop handed the mission back as an
            # AbortedMission (equinor/isar#1176).
            LOW_BATTERY_DURING_MISSION.name: "RechargingWithMission",
        },
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )
    # The idle robot finished its mission before running low; the other
    # robot's mission is resumed once it has recharged.
    wait_for_all_mission_run_statuses(
        backend_url,
        {mission_runs[robot.name]["id"]: "Successful" for robot in ROSTER},
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )
    wait_for_all_robot_statuses(
        backend_url,
        {robot.name: "Home" for robot in ROSTER},
        timeout=TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )
