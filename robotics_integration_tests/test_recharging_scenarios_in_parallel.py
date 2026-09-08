"""Recharging, run as two robots in parallel on one armada.

A robot that runs low on battery must take itself off to charge and then pick up
where it left off. This covers five previously untested states:
``StoppingGoToRecharge``, ``GoingToRecharging``, ``GoingToRechargingWithMission``,
``Recharging`` and ``RechargingWithMission``.

The with-mission variant also exercises the branch introduced by equinor/isar#1176
in ``stopping_go_to_recharge.py``, where a single ``stop_mission.success`` event
carries either an ``AbortedMission`` or an empty message and the state machine
picks the destination by inspecting the payload. The idle robot takes the empty
branch, the interrupted robot takes the ``AbortedMission`` branch.

Battery behaviour in isar-robot is a simple ramp: it falls 0.4 per publish while
away from home and rises 2.0 per publish while home. Rather than wait for the
default 75 % to drift down, each robot boots at a level chosen so its threshold
crossing lands where the scenario needs it. That requires isar-robot with
ROBOT_INITIAL_BATTERY_LEVEL.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.utilities import isar_status
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
)

# Long tasks, so the mission is still running when the battery gives out.
SLOW_TASK_DURATION_SECONDS = 70.0

# One battery sample per second, and ISAR reading it just as often, so a crossing
# is noticed within a second of happening. isar-robot discharges 0.4 per sample
# away from home and charges 2.0 per sample at home, so at this interval the level
# falls 0.4 %/s and rises 2 %/s.
BATTERY_PUBLISH_INTERVAL = "1"
BATTERY_POLL_INTERVAL = "1"

# ISAR's default mission threshold is 25 %. The recharge threshold has to leave
# enough headroom for the robot to finish what is left of the interrupted mission
# after charging, or it drops back below 25 % and recharges in a loop. One
# remaining task drains 28 % at this task duration, so 85 % is ample.
RECHARGE_THRESHOLD = "85"

# Long enough that neither robot returns home on its own before its battery
# crosses the threshold. A robot that reaches home starts charging, which would
# stop the level from ever falling.
LONG_RETURN_HOME_DELAY = "600"

# The idle robot boots away from home and starts discharging immediately, so 27 %
# falls past the 25 % threshold within seconds. It has no mission to wait for.
IDLE_ROBOT_INITIAL_BATTERY = 27.0

# The mission robot boots *at* home on a full battery, and stays full because a
# robot at home charges. That pins the start of the discharge to the moment it
# leaves home on the mission, rather than to container boot: 100 % falls past
# 25 % after 187 s, which lands in the third of three seventy second tasks.
#
# Booting at home also matters for dispatch. Flotilla reliably hands a mission to
# a robot that is Home; a robot idling in AwaitNextMission may sit Queued instead.
MISSION_ROBOT_INITIAL_BATTERY = 100.0

LOW_BATTERY_WHILE_IDLE = "LowBatteryWhileIdle"
LOW_BATTERY_DURING_MISSION = "LowBatteryDuringMission"


def _battery_robot(
    name: str, alias: str, initial_battery: float, start_at_home: bool
) -> RobotScenario:
    return RobotScenario(
        name=name,
        alias=alias,
        should_start_at_home=start_at_home,
        task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
        initial_battery_level=initial_battery,
        extra_environment={
            "ROBOT_ROBOT_BATTERY_PUBLISH_INTERVAL": BATTERY_PUBLISH_INTERVAL,
            "ISAR_ROBOT_API_BATTERY_POLL_INTERVAL": BATTERY_POLL_INTERVAL,
            "ISAR_ROBOT_BATTERY_RECHARGE_THRESHOLD": RECHARGE_THRESHOLD,
            "ISAR_RETURN_HOME_DELAY": LONG_RETURN_HOME_DELAY,
        },
    )


def test_recharging_scenarios_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster(
        [
            _battery_robot(
                LOW_BATTERY_WHILE_IDLE,
                "isar_low_battery_while_idle",
                IDLE_ROBOT_INITIAL_BATTERY,
                start_at_home=False,
            ),
            _battery_robot(
                LOW_BATTERY_DURING_MISSION,
                "isar_low_battery_during_mission",
                MISSION_ROBOT_INITIAL_BATTERY,
                start_at_home=True,
            ),
        ]
    )
    backend_url: str = armada.flotilla_backend.backend_url
    recorder = armada.mqtt_recorder

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

    # Confirm the mission is genuinely under way before the battery runs down, so
    # that the robot is in Monitor rather than still dispatching when it crosses.
    # The mission run going Ongoing is the right signal: with sixty second tasks
    # the battery can cross before the second task ever starts.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Ongoing",
        timeout=180,
    )

    # The idle robot has no mission, so it goes straight to recharging.
    recorder.wait_for_state(
        LOW_BATTERY_WHILE_IDLE, isar_status.GOING_TO_RECHARGING, timeout=180
    )
    recorder.wait_for_state(LOW_BATTERY_WHILE_IDLE, isar_status.RECHARGING, timeout=240)

    # The busy robot must stop its mission first, and carry it into recharging.
    recorder.wait_for_state(
        LOW_BATTERY_DURING_MISSION,
        isar_status.GOING_TO_RECHARGING_WITH_MISSION,
        timeout=420,
    )
    recorder.wait_for_state(
        LOW_BATTERY_DURING_MISSION,
        isar_status.RECHARGING_WITH_MISSION,
        timeout=420,
    )

    # Charging past the recharge threshold must hand the mission back and let it
    # finish. This is what proves the aborted mission was carried through the
    # recharge cycle rather than dropped.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Successful",
        timeout=420,
    )

    # Settle first, then assert the traces: a trace is only complete once the
    # robots have reached their final state.
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            LOW_BATTERY_WHILE_IDLE: "Home",
            LOW_BATTERY_DURING_MISSION: "Home",
        },
        timeout=420,
    )

    recorder.assert_visited_in_order(
        LOW_BATTERY_WHILE_IDLE,
        [
            isar_status.AVAILABLE,
            isar_status.GOING_TO_RECHARGING,
            isar_status.RECHARGING,
            isar_status.HOME,
        ],
    )
    recorder.assert_visited_in_order(
        LOW_BATTERY_DURING_MISSION,
        [
            isar_status.BUSY,
            # StoppingGoToRecharge: the mission is stopped and handed on as an
            # AbortedMission, which is what selects the with-mission states.
            isar_status.STOPPING,
            isar_status.GOING_TO_RECHARGING_WITH_MISSION,
            isar_status.RECHARGING_WITH_MISSION,
            # Monitor again, finishing the interrupted mission.
            isar_status.BUSY,
        ],
    )
