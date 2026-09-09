"""Lockdown, run as two robots in parallel on one armada.

Lockdown is the emergency path: an operator aborts everything on an installation
and sends the robots to a safe place. It was entirely uncovered, and it is the
largest untested cluster in ISAR's state machine — ``StoppingGoToLockdown``,
``GoingToLockdown``, ``GoingToLockdownWithMission``, ``Lockdown`` and
``LockdownWithMission``.

The two robots differ in whether they were running a mission when lockdown hit,
which is what selects the with-mission variants. Flotilla reports both variants as plain
``Lockdown``, so they are told apart by what happens on release: the idle robot
goes home, while the interrupted robot must resume and finish its mission.

Assertions are made against Flotilla over REST and only on resting statuses.
``GoingToLockdown`` and the ``Stopping`` that precedes it are transient and are
not asserted.

Lockdown is driven straight against each ISAR robot rather than through Flotilla's
emergency action. Flotilla currently subscribes both its lockdown and its release
handler to the same event and neither tells them apart, so releasing an
installation frees the robots and immediately locks them again; see
utilities/isar_api.py. The states under test are ISAR's either way.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_all_robot_statuses,
    wait_for_mission_run_status,
    wait_for_robot_status,
    wait_for_robot_status_sequences,
    wait_for_second_task_status_of_mission_run,
)
from robotics_integration_tests.utilities.isar_api import (
    release_from_lockdown,
    send_to_lockdown,
)

SLOW_TASK_DURATION_SECONDS = 20.0

# The idle robot must not wander home on its own before lockdown is triggered.
LONG_RETURN_HOME_DELAY_SECONDS = "600"

# Robots that boot away from home discharge steadily, and a long test can drift
# past ISAR's default 25 % mission threshold and divert into recharging. These
# scenarios are not about battery, so the threshold is pinned out of the way.
NO_BATTERY_INTERFERENCE = {"ISAR_ROBOT_MISSION_BATTERY_START_THRESHOLD": "0"}

LOCKDOWN_WHILE_IDLE = "LockdownWhileIdle"
LOCKDOWN_DURING_MISSION = "LockdownDuringMission"


def test_lockdown_scenarios_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster(
        [
            # Boots away from home, so it sits in AwaitNextMission and has to
            # travel back when locked down. A robot that is already Home enters
            # Lockdown directly and never passes through GoingToLockdown.
            RobotScenario(
                name=LOCKDOWN_WHILE_IDLE,
                alias="isar_lockdown_while_idle",
                should_start_at_home=False,
                task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
                extra_environment={
                    "ISAR_RETURN_HOME_DELAY": LONG_RETURN_HOME_DELAY_SECONDS,
                    **NO_BATTERY_INTERFERENCE,
                },
            ),
            RobotScenario(
                name=LOCKDOWN_DURING_MISSION,
                alias="isar_lockdown_during_mission",
                task_duration_in_seconds=SLOW_TASK_DURATION_SECONDS,
                extra_environment=dict(NO_BATTERY_INTERFERENCE),
            ),
        ]
    )
    backend_url: str = armada.flotilla_backend.backend_url

    idle_robot = armada.robots[LOCKDOWN_WHILE_IDLE]
    interrupted_robot = armada.robots[LOCKDOWN_DURING_MISSION]
    installation_code: str = interrupted_robot.installation_code

    # Only the second robot gets a mission; the first is left idle so that the
    # same lockdown call exercises both the with-mission and the plain path.
    mission_payload: Dict = get_dummy_mission_payload_with_installation(
        installation_code
    )
    mission: Dict = create_mission(backend_url=backend_url, payload=mission_payload)
    interrupted_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=interrupted_robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(
        f"Scheduled mission run {interrupted_run['id']} on {LOCKDOWN_DURING_MISSION}"
    )

    wait_for_second_task_status_of_mission_run(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="InProgress",
    )

    # The idle robot must be confirmed idle *before* lockdown is triggered.
    # Available is a resting state only until something acts on the robot, so
    # asserting it after the trigger would race the transition out of it.
    wait_for_robot_status(
        backend_url=backend_url,
        robot_name=LOCKDOWN_WHILE_IDLE,
        expected_status="Available",
        timeout=240,
    )

    send_to_lockdown(idle_robot)
    send_to_lockdown(interrupted_robot)

    # Both robots must come to rest in lockdown before anything is released,
    # otherwise the release could race the lockdown itself. Lockdown rests until
    # an operator releases it, so it is safe to assert over REST.
    wait_for_robot_status_sequences(
        backend_url=backend_url,
        status_expectations={
            LOCKDOWN_WHILE_IDLE: ["Lockdown"],
            LOCKDOWN_DURING_MISSION: ["Lockdown"],
        },
        timeout=240,
    )

    release_from_lockdown(idle_robot)
    release_from_lockdown(interrupted_robot)

    # The interrupted mission must be handed back and run to completion. That is
    # what separates LockdownWithMission from a plain Lockdown: only the
    # with-mission variant has a mission to resume on release.
    wait_for_mission_run_status(
        backend_url=backend_url,
        mission_run_id=interrupted_run["id"],
        expected_status="Successful",
        timeout=300,
    )

    wait_for_all_robot_statuses(
        backend_url=backend_url,
        robot_status_expectations={
            LOCKDOWN_WHILE_IDLE: "Home",
            LOCKDOWN_DURING_MISSION: "Home",
        },
        timeout=300,
    )
