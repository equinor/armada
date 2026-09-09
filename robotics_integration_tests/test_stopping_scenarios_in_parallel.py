"""Four ways a mission is brought to a halt, run as four robots in parallel.

ISAR reaches a different state for each, and none of them were covered before:
``Stopping``, ``StoppingPausedMission``, ``StoppingReturnHome`` and
``StoppingPausedReturnHome``. They are grouped onto a single stack because an
armada costs roughly twelve containers before any robot is added, so four separate
tests would cost four of those.

Only the first two are operator stops. A return home cannot be stopped: neither
``ReturningHome`` nor ``ReturnHomePaused`` handles ``stop_mission``, and the only
control an operator has over a return home is to pause and resume it. Those two
states are instead reached by *scheduling a mission*, which supersedes the return
home; ISAR stops the return-home mission internally to start the new one.

Each robot is verified against Flotilla's view of it over REST, and only on
statuses the robot genuinely rests in. The ``Stopping*`` states themselves are
transient and are deliberately not asserted; what proves each stop happened is
the resulting mission run status. ``Cancelled`` means the operator's stop took
effect, and ``Successful`` on a mission scheduled during a return home means the
return home was superseded rather than the mission being refused.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    pause_mission,
    schedule_mission,
    schedule_return_to_home,
    stop_mission,
    wait_for_all_robot_statuses,
    wait_for_robot_status,
    wait_for_mission_run_status,
    wait_for_second_task_status_of_mission_run,
)

# Tasks are stretched so that every scenario has a comfortable window in which to
# interfere with a running mission. The dummy mission has three tasks, so a
# mission lasts roughly a minute rather than fifteen seconds.
SLOW_TASK_DURATION_SECONDS = 15.0

# ISAR waits this long in AwaitNextMission before returning home on its own.
SHORT_RETURN_HOME_DELAY_SECONDS = "5"

# The return-home scenarios trigger the return home themselves, so ISAR must not
# start one on its own first and win the race.
LONG_RETURN_HOME_DELAY_SECONDS = "600"

# Robots that boot away from home discharge steadily, and a long test can drift
# past ISAR's default 25 % mission threshold and divert into recharging. These
# scenarios are not about battery, so the threshold is pinned out of the way.
NO_BATTERY_INTERFERENCE = {"ISAR_ROBOT_MISSION_BATTERY_START_THRESHOLD": "0"}

STOP_DURING_MISSION = "StopDuringMission"
STOP_WHILE_PAUSED = "StopWhilePaused"
MISSION_WHILE_RETURNING_HOME = "MissionWhileReturningHome"
MISSION_WHILE_RETURN_HOME_PAUSED = "MissionWhileReturnHomePaused"


def _mission_robot(name: str, alias: str) -> RobotScenario:
    """A robot that boots at home, ready to be given a mission."""
    return RobotScenario(
        name=name,
        alias=alias,
        task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
        extra_environment={
            "ISAR_RETURN_HOME_DELAY": SHORT_RETURN_HOME_DELAY_SECONDS,
            **NO_BATTERY_INTERFERENCE,
        },
    )


def _return_home_robot(name: str, alias: str) -> RobotScenario:
    """A robot that boots *away* from home, so a return home actually runs.

    A robot that is already home rejects a return-home mission with
    RobotAlreadyHomeException, which ISAR treats as instant success. It would
    therefore pass straight back through ReturningHome without ever resting there,
    leaving no window for the test to pause or interrupt it.
    """
    return RobotScenario(
        name=name,
        alias=alias,
        should_start_at_home=False,
        task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
        extra_environment={
            "ISAR_RETURN_HOME_DELAY": LONG_RETURN_HOME_DELAY_SECONDS,
            **NO_BATTERY_INTERFERENCE,
        },
    )


def _schedule_dummy_mission(armada: Armada, robot_name: str) -> Dict:
    robot = armada.robots[robot_name]
    backend_url: str = armada.flotilla_backend.backend_url

    mission_payload: Dict = get_dummy_mission_payload_with_installation(
        robot.installation_code
    )
    mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
    mission_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(
        f"Scheduled mission {mission['id']} with run id {mission_run['id']} "
        f"on robot {robot_name}"
    )
    return mission_run


def test_stopping_scenarios_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster(
        [
            _mission_robot(STOP_DURING_MISSION, "isar_stop_during_mission"),
            _mission_robot(STOP_WHILE_PAUSED, "isar_stop_while_paused"),
            _return_home_robot(
                MISSION_WHILE_RETURNING_HOME, "isar_mission_while_returning_home"
            ),
            _return_home_robot(
                MISSION_WHILE_RETURN_HOME_PAUSED,
                "isar_mission_while_return_home_paused",
            ),
        ]
    )
    backend_url: str = armada.flotilla_backend.backend_url

    # ---------------------------------------------------------------- scenario 1
    # Monitor -> Stopping -> AwaitNextMission. The stop carries the unfinished
    # tasks back to the state machine as an AbortedMission.
    stop_during_mission_run: Dict = _schedule_dummy_mission(armada, STOP_DURING_MISSION)
    wait_for_second_task_status_of_mission_run(
        backend_url=backend_url,
        mission_run_id=stop_during_mission_run["id"],
        expected_status="InProgress",
        timeout=180,
    )
    stop_mission(
        backend_url=backend_url, robot_id=armada.robots[STOP_DURING_MISSION].robot_id
    )

    # ---------------------------------------------------------------- scenario 2
    # Monitor -> Pausing -> Paused -> StoppingPausedMission -> AwaitNextMission.
    stop_while_paused_run: Dict = _schedule_dummy_mission(armada, STOP_WHILE_PAUSED)
    wait_for_second_task_status_of_mission_run(
        backend_url=backend_url,
        mission_run_id=stop_while_paused_run["id"],
        expected_status="InProgress",
        timeout=180,
    )
    pause_mission(
        backend_url=backend_url, robot_id=armada.robots[STOP_WHILE_PAUSED].robot_id
    )
    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=STOP_WHILE_PAUSED,
        expected_status="Paused",
        timeout=180,
    )
    stop_mission(
        backend_url=backend_url, robot_id=armada.robots[STOP_WHILE_PAUSED].robot_id
    )

    # ---------------------------------------------------------------- scenario 3
    # ReturningHome -> StoppingReturnHome -> Monitor. There is no way to stop a
    # return home; scheduling a mission supersedes it, and ISAR stops the
    # return-home mission internally to start the new one.
    returning_home_robot = armada.robots[MISSION_WHILE_RETURNING_HOME]
    schedule_return_to_home(
        backend_url=backend_url, robot_id=returning_home_robot.robot_id
    )
    # Synchronisation, not a coverage assertion: the mission must not be
    # scheduled until the return home is genuinely under way. ReturningHome lasts
    # as long as the return-home mission, so it is comfortably pollable.
    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=MISSION_WHILE_RETURNING_HOME,
        expected_status="ReturningHome",
        timeout=240,
    )
    interrupting_run: Dict = _schedule_dummy_mission(
        armada, MISSION_WHILE_RETURNING_HOME
    )

    # ---------------------------------------------------------------- scenario 4
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused ->
    # StoppingPausedReturnHome -> Monitor. Pause and resume are the only controls
    # ISAR offers over a return home, so the paused return home is likewise
    # superseded by scheduling a mission rather than stopped.
    return_home_paused_robot = armada.robots[MISSION_WHILE_RETURN_HOME_PAUSED]
    schedule_return_to_home(
        backend_url=backend_url, robot_id=return_home_paused_robot.robot_id
    )
    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=MISSION_WHILE_RETURN_HOME_PAUSED,
        expected_status="ReturningHome",
        timeout=240,
    )
    pause_mission(backend_url=backend_url, robot_id=return_home_paused_robot.robot_id)
    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=MISSION_WHILE_RETURN_HOME_PAUSED,
        expected_status="ReturnHomePaused",
        timeout=240,
    )
    resuming_run: Dict = _schedule_dummy_mission(
        armada, MISSION_WHILE_RETURN_HOME_PAUSED
    )

    # ------------------------------------------------------------------ outcomes
    # The two stopped missions must end Cancelled; the two that interrupted a
    # return home must go on to complete, which is what proves the state machine
    # started them rather than merely aborting the return home.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=stop_during_mission_run["id"],
        expected_status="Cancelled",
        timeout=180,
    )
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=stop_while_paused_run["id"],
        expected_status="Cancelled",
        timeout=180,
    )
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupting_run["id"],
        expected_status="Successful",
        timeout=180,
    )
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=resuming_run["id"],
        expected_status="Successful",
        timeout=180,
    )

    # These two robots were given a long return-home delay so that ISAR would not
    # start a return home of its own before the test superseded one. That delay is
    # still in force now their missions have finished, so they would sit in
    # AwaitNextMission for ten minutes; ask them to go home explicitly instead.
    schedule_return_to_home(
        backend_url=backend_url,
        robot_id=armada.robots[MISSION_WHILE_RETURNING_HOME].robot_id,
    )
    schedule_return_to_home(
        backend_url=backend_url,
        robot_id=armada.robots[MISSION_WHILE_RETURN_HOME_PAUSED].robot_id,
    )

    # Every robot must settle back at home rather than needing an operator.
    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            STOP_DURING_MISSION: "Home",
            STOP_WHILE_PAUSED: "Home",
            MISSION_WHILE_RETURNING_HOME: "Home",
            MISSION_WHILE_RETURN_HOME_PAUSED: "Home",
        },
        timeout=180,
    )
