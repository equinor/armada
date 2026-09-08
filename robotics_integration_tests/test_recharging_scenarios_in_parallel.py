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
    wait_for_second_task_status_of_mission_run,
)

SLOW_TASK_DURATION_SECONDS = 20.0

# One battery sample per second, and ISAR reading it just as often, so a crossing
# is noticed within a second of happening.
BATTERY_PUBLISH_INTERVAL = "1"
BATTERY_POLL_INTERVAL = "1"

# ISAR's default mission threshold is 25 %. The recharge threshold is raised well
# above it so that a robot which has just charged has enough headroom to finish
# its remaining tasks without immediately dropping below the threshold again and
# looping.
RECHARGE_THRESHOLD = "60"

# Long enough that neither robot returns home on its own before its battery
# crosses the threshold. A robot that reaches home starts charging, which would
# stop the level from ever falling.
LONG_RETURN_HOME_DELAY = "600"

# 27 % falls past the 25 % threshold in about five seconds of discharging.
IDLE_ROBOT_INITIAL_BATTERY = 27.0

# 40 % takes about 38 seconds to fall past 25 %, which lands partway through a
# three task mission of twenty seconds per task.
MISSION_ROBOT_INITIAL_BATTERY = 40.0

LOW_BATTERY_WHILE_IDLE = "LowBatteryWhileIdle"
LOW_BATTERY_DURING_MISSION = "LowBatteryDuringMission"


def _battery_robot(name: str, alias: str, initial_battery: float) -> RobotScenario:
    return RobotScenario(
        name=name,
        alias=alias,
        # The robot must boot away from home, otherwise it charges from the start
        # and the battery never falls.
        should_start_at_home=False,
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
            ),
            _battery_robot(
                LOW_BATTERY_DURING_MISSION,
                "isar_low_battery_during_mission",
                MISSION_ROBOT_INITIAL_BATTERY,
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
    wait_for_second_task_status_of_mission_run(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="InProgress",
        timeout=120,
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
        timeout=240,
    )
    recorder.wait_for_state(
        LOW_BATTERY_DURING_MISSION,
        isar_status.RECHARGING_WITH_MISSION,
        timeout=300,
    )

    # Charging past the recharge threshold must hand the mission back and let it
    # finish. This is what proves the aborted mission was carried through the
    # recharge cycle rather than dropped.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Successful",
        timeout=300,
    )

    # Settle first, then assert the traces: a trace is only complete once the
    # robots have reached their final state.
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            LOW_BATTERY_WHILE_IDLE: "Home",
            LOW_BATTERY_DURING_MISSION: "Home",
        },
        timeout=300,
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
