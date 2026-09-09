"""Recharging, run as two robots in parallel on one armada.

A robot that runs low on battery must take itself off to charge and then pick up
where it left off. This drives ISAR through ``StoppingGoToRecharge``,
``GoingToRecharging``, ``GoingToRechargingWithMission``, ``Recharging`` and
``RechargingWithMission``.

The with-mission variant exercises the branch introduced by equinor/isar#1176 in
``stopping_go_to_recharge.py``, where a single ``stop_mission.success`` event
carries either an ``AbortedMission`` or an empty message and the state machine
picks the destination by inspecting the payload. ``RechargingWithMission`` is only
reachable through the ``AbortedMission`` branch, so asserting the robot rests
there is what covers it.

Assertions are made against Flotilla's view of the robot over REST, and only on
statuses the robot genuinely rests in. ``GoingToRecharging`` and
``GoingToRechargingWithMission`` are deliberately not asserted: they last only as
long as the return-home mission and could fall between two polls.

Battery behaviour in isar-robot is a simple ramp: the level falls 0.4 per
telemetry sample away from home and rises 2.0 per sample while at home, so at a
one second publish interval it falls 0.4 %/s and rises 2 %/s. Each robot boots at
a level chosen so its threshold crossing lands where the scenario needs it, which
requires isar-robot with ROBOT_INITIAL_BATTERY_LEVEL.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status_sequences,
)

SLOW_TASK_DURATION_SECONDS = 25.0

# One battery sample per second, and ISAR reading it just as often, so a crossing
# is noticed within a second of happening.
BATTERY_PUBLISH_INTERVAL = "1"
BATTERY_POLL_INTERVAL = "1"

# Keeps the idle robot in AwaitNextMission rather than letting it wander home,
# where it would charge and never cross the threshold. It also makes Available a
# resting state for that robot, and so safe to assert.
LONG_RETURN_HOME_DELAY = "600"

LOW_BATTERY_WHILE_IDLE = "LowBatteryWhileIdle"
LOW_BATTERY_DURING_MISSION = "LowBatteryDuringMission"


def _idle_robot() -> RobotScenario:
    """Boots away from home with just enough charge to reach the threshold.

    35 % rather than something nearer the 25 % threshold: at 0.4 %/s that is a
    25 second run, which leaves Available observable for long enough to assert.
    Starting at 27 % would cross about five seconds after boot and race ISAR's own
    five second status poll, leaving Available visible for under a second.

    The recharge threshold is only 50 % so charging is short; this robot has no
    mission to finish afterwards, so it needs no headroom.
    """
    return RobotScenario(
        name=LOW_BATTERY_WHILE_IDLE,
        alias="isar_low_battery_while_idle",
        should_start_at_home=False,
        task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
        initial_battery_level=35.0,
        extra_environment={
            "ROBOT_ROBOT_BATTERY_PUBLISH_INTERVAL": BATTERY_PUBLISH_INTERVAL,
            "ISAR_ROBOT_API_BATTERY_POLL_INTERVAL": BATTERY_POLL_INTERVAL,
            "ISAR_ROBOT_BATTERY_RECHARGE_THRESHOLD": "50",
            "ISAR_RETURN_HOME_DELAY": LONG_RETURN_HOME_DELAY,
        },
    )


def _mission_robot() -> RobotScenario:
    """Boots at home on a full battery and only starts discharging on departure.

    A robot at home charges, so booting there pins the battery at 100 % until the
    mission dispatches. That anchors the discharge to the start of the mission
    rather than to container boot, which is what makes the crossing land
    predictably: (100 - 75) / 0.4 = 62.5 s into a 75 s mission, part way through
    the third of three tasks.

    A high mission threshold shortens that discharge; a high recharge threshold
    then leaves enough charge to finish the final task and get home afterwards.
    Unlike the idle robot this one keeps ISAR's default return-home delay, so it
    goes home promptly once the mission is done.
    """
    return RobotScenario(
        name=LOW_BATTERY_DURING_MISSION,
        alias="isar_low_battery_during_mission",
        should_start_at_home=True,
        task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
        initial_battery_level=100.0,
        extra_environment={
            "ROBOT_ROBOT_BATTERY_PUBLISH_INTERVAL": BATTERY_PUBLISH_INTERVAL,
            "ISAR_ROBOT_API_BATTERY_POLL_INTERVAL": BATTERY_POLL_INTERVAL,
            "ISAR_ROBOT_MISSION_BATTERY_START_THRESHOLD": "75",
            "ISAR_ROBOT_BATTERY_RECHARGE_THRESHOLD": "96",
        },
    )


def test_recharging_scenarios_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster([_idle_robot(), _mission_robot()])
    backend_url: str = armada.flotilla_backend.backend_url

    mission_robot = armada.robots[LOW_BATTERY_DURING_MISSION]

    mission_payload: Dict = get_dummy_mission_payload_with_installation(
        mission_robot.installation_code
    )
    mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
    interrupted_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=mission_robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(
        f"Scheduled mission run {interrupted_run['id']} on {LOW_BATTERY_DURING_MISSION}"
    )

    # Both robots are tracked in one polling loop. Waiting on them one after the
    # other would risk the second robot passing through its window while the
    # first is still being polled: the idle robot charges at roughly 70 s, and the
    # mission robot reaches RechargingWithMission at roughly 120 s.
    #
    # RechargingWithMission is reachable only when the stop that preceded it
    # handed back an AbortedMission, so resting there is what proves the mission
    # was carried into the recharge rather than dropped.
    wait_for_robot_status_sequences(
        backend_url=backend_url,
        status_expectations={
            LOW_BATTERY_WHILE_IDLE: ["Available", "Recharging", "Home"],
            LOW_BATTERY_DURING_MISSION: ["RechargingWithMission", "Home"],
        },
        timeout=420,
    )

    # The interrupted mission must then be handed back and run to completion.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Successful",
        timeout=420,
    )
