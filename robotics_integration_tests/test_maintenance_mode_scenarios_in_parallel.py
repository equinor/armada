"""Maintenance mode, run as two robots in parallel on one armada.

Maintenance is how an operator takes a robot out of service. It covers two
previously untested states: ``StoppingDueToMaintenance``, reached only when the
robot was mid-mission, and ``Maintenance`` itself.

Releasing maintenance sends ISAR to ``UnknownStatus``, where it re-derives the
robot's real state from a status poll — so the release path also exercises the
status-driven recovery that ``UnknownStatus`` exists for.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.utilities import isar_status
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    release_maintenance_mode,
    schedule_mission,
    set_maintenance_mode,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
    wait_for_second_task_status_of_mission_run,
)

SLOW_TASK_DURATION_SECONDS = 20.0

MAINTENANCE_WHILE_IDLE = "MaintenanceWhileIdle"
MAINTENANCE_DURING_MISSION = "MaintenanceDuringMission"


def test_maintenance_mode_scenarios_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster(
        [
            RobotScenario(
                name=MAINTENANCE_WHILE_IDLE,
                alias="isar_maintenance_while_idle",
                task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
            ),
            RobotScenario(
                name=MAINTENANCE_DURING_MISSION,
                alias="isar_maintenance_during_mission",
                task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
            ),
        ]
    )
    backend_url: str = armada.flotilla_backend.backend_url
    recorder = armada.mqtt_recorder

    idle_robot = armada.robots[MAINTENANCE_WHILE_IDLE]
    busy_robot = armada.robots[MAINTENANCE_DURING_MISSION]

    # Only the second robot gets a mission, so that one robot enters maintenance
    # directly and the other has to stop a mission on the way in.
    mission_payload: Dict = get_dummy_mission_payload_with_installation(
        busy_robot.installation_code
    )
    mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
    interrupted_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=busy_robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(
        f"Scheduled mission run {interrupted_run['id']} on {MAINTENANCE_DURING_MISSION}"
    )

    wait_for_second_task_status_of_mission_run(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="InProgress",
    )

    set_maintenance_mode(backend_url=backend_url, robot_id=idle_robot.robot_id)
    set_maintenance_mode(backend_url=backend_url, robot_id=busy_robot.robot_id)

    recorder.wait_for_state(
        MAINTENANCE_WHILE_IDLE, isar_status.MAINTENANCE, timeout=180
    )
    recorder.wait_for_state(
        MAINTENANCE_DURING_MISSION, isar_status.MAINTENANCE, timeout=180
    )

    # A mission interrupted by maintenance is abandoned rather than resumed, which
    # is the opposite of the lockdown contract. Note ISAR announces this on its
    # mission_aborted topic rather than as a Cancelled mission status, so Flotilla
    # records it as Aborted; a mission the operator stops explicitly is Cancelled.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Aborted",
        timeout=180,
    )

    release_maintenance_mode(backend_url=backend_url, robot_id=idle_robot.robot_id)
    release_maintenance_mode(backend_url=backend_url, robot_id=busy_robot.robot_id)

    # Settle first, then assert the traces: a trace is only complete once the
    # robots have reached their final state.
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            MAINTENANCE_WHILE_IDLE: "Home",
            MAINTENANCE_DURING_MISSION: "Home",
        },
        timeout=240,
    )

    recorder.assert_visited_in_order(
        MAINTENANCE_WHILE_IDLE,
        [isar_status.MAINTENANCE, isar_status.HOME],
    )
    recorder.assert_visited_in_order(
        MAINTENANCE_DURING_MISSION,
        [
            isar_status.BUSY,
            # StoppingDueToMaintenance: the running mission is stopped first.
            isar_status.STOPPING,
            isar_status.MAINTENANCE,
            isar_status.HOME,
        ],
    )
