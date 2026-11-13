"""A robot's steps: wait for a condition, then optionally act on that robot."""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot, RobotScenario
from robotics_integration_tests.utilities import flotilla_backend_api as flotilla

POLL_INTERVAL_IN_SECONDS: float = 1.0

STATUSES_A_ROBOT_RESTS_IN = frozenset(
    {"Home", "Paused", "ReturnHomePaused", "Lockdown", "Maintenance"}
    | {"InterventionNeeded"}
)
# Available lasts for the return-home delay, ReturningHome for the return-home
# mission, and the recharging statuses until the battery is charged.
STATUSES_THAT_LAST_FOR_SEVERAL_POLLS = frozenset(
    {"Available", "ReturningHome", "Recharging", "RechargingWithMission"}
)
POLLABLE_ROBOT_STATUSES = (
    STATUSES_A_ROBOT_RESTS_IN | STATUSES_THAT_LAST_FOR_SEVERAL_POLLS
)


@dataclass
class RobotContext:
    """What a robot's steps can see and act on."""

    armada: Armada
    robot: IsarRobot
    # The robot's status in Flotilla as of the current poll.
    status: Optional[str] = None
    # Every mission run scheduled by this robot's steps, oldest first.
    mission_runs: List[Dict] = field(default_factory=list)
    # Each distinct status seen, in order. Reported when a step times out.
    observed_statuses: List[str] = field(default_factory=list)

    @property
    def backend_url(self) -> str:
        return self.armada.flotilla_backend.backend_url


@dataclass(frozen=True)
class Condition:
    description: str
    is_met: Callable[[RobotContext], bool]


Action = Callable[[RobotContext], None]


@dataclass(frozen=True)
class Step:
    wait_for: Condition
    then: Optional[Action] = None
    # Counted from when the robot's previous step completed.
    timeout_in_seconds: float = 240.0


immediately = Condition("immediately", lambda context: True)


def robot_status(expected_status: str) -> Condition:
    if expected_status not in POLLABLE_ROBOT_STATUSES:
        raise ValueError(
            f"'{expected_status}' can pass between two polls of Flotilla. Wait "
            f"for the mission run status it leads to instead, or for one of "
            f"{sorted(POLLABLE_ROBOT_STATUSES)}."
        )
    return Condition(
        f"robot status {expected_status}",
        lambda context: context.status == expected_status,
    )


robot_is_idle_away_from_home = robot_status("Available")


def mission_status(expected_status: str, run: int = -1) -> Condition:
    """The status of a mission run this robot scheduled, by default its latest."""

    def is_met(context: RobotContext) -> bool:
        mission_run: Dict = flotilla.get_mission_run_by_id(
            backend_url=context.backend_url,
            mission_run_id=context.mission_runs[run]["id"],
        )
        return mission_run.get("status") == expected_status

    return Condition(f"mission run [{run}] status {expected_status}", is_met)


def _second_task_of_latest_mission_is_in_progress(context: RobotContext) -> bool:
    mission_run: Dict = flotilla.get_mission_run_by_id(
        backend_url=context.backend_url,
        mission_run_id=context.mission_runs[-1]["id"],
    )
    return mission_run["tasks"][1].get("status") == "InProgress"


mission_is_under_way_with_tasks_left = Condition(
    "mission is under way with tasks left",
    _second_task_of_latest_mission_is_in_progress,
)


def schedule_dummy_mission(context: RobotContext) -> None:
    context.mission_runs.append(
        flotilla.schedule_dummy_mission(
            backend_url=context.backend_url,
            robot_id=context.robot.robot_id,
            installation_code=context.robot.installation_code,
        )
    )


def pause_mission(context: RobotContext) -> None:
    flotilla.pause_mission(context.backend_url, context.robot.robot_id)


def stop_mission(context: RobotContext) -> None:
    flotilla.stop_mission(context.backend_url, context.robot.robot_id)


def schedule_return_to_home(context: RobotContext) -> None:
    flotilla.schedule_return_to_home(context.backend_url, context.robot.robot_id)


def set_maintenance_mode(context: RobotContext) -> None:
    flotilla.set_maintenance_mode(context.backend_url, context.robot.robot_id)


def release_maintenance_mode(context: RobotContext) -> None:
    flotilla.release_maintenance_mode(context.backend_url, context.robot.robot_id)


@dataclass
class _Progress:
    context: RobotContext
    remaining: Deque[Step]
    total: int
    step_started: float
    failure: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.failure is None and bool(self.remaining)

    @property
    def position(self) -> str:
        return f"step {self.total - len(self.remaining) + 1} of {self.total}"


def _observe(context: RobotContext, status: Optional[str]) -> None:
    context.status = status
    if status is None:
        return
    seen: List[str] = context.observed_statuses
    if not seen or seen[-1] != status:
        seen.append(status)
        logger.info(f"[{context.robot.name}] is in status '{status}'")


def _advance(progress: _Progress) -> None:
    """Complete as many of the robot's steps as are already satisfied.

    Stops after an action, since the polled status no longer reflects the robot.
    """
    context: RobotContext = progress.context
    name: str = context.robot.name

    while progress.remaining:
        step: Step = progress.remaining[0]
        try:
            is_met: bool = step.wait_for.is_met(context)
        except Exception as error:
            logger.warning(
                f"[{name}] could not check '{step.wait_for.description}', "
                f"will retry: {error}"
            )
            is_met = False

        if not is_met:
            waited: float = time.monotonic() - progress.step_started
            if waited > step.timeout_in_seconds:
                progress.failure = (
                    f"{progress.position}: '{step.wait_for.description}' was not "
                    f"met within {step.timeout_in_seconds:g}s. "
                    f"Statuses observed: {context.observed_statuses}"
                )
            return

        logger.info(f"[{name}] {progress.position}: {step.wait_for.description}")
        if step.then is not None:
            try:
                step.then(context)
            except Exception as error:
                progress.failure = (
                    f"{progress.position}: {step.then.__name__} failed: {error}"
                )
                return

        progress.remaining.popleft()
        progress.step_started = time.monotonic()
        if step.then is not None:
            return


def advance_each_robot_through_its_own_steps(
    armada: Armada, roster: List[RobotScenario]
) -> Dict[str, RobotContext]:
    """Poll all robots in one loop and return each robot's context.

    A robot that fails stops there while the others carry on, so a single run
    reports every failing robot.
    """
    backend_url: str = armada.flotilla_backend.backend_url
    started: float = time.monotonic()
    progress_by_robot: Dict[str, _Progress] = {
        scenario.name: _Progress(
            context=RobotContext(armada=armada, robot=armada.robots[scenario.name]),
            remaining=deque(scenario.steps),
            total=len(scenario.steps),
            step_started=started,
        )
        for scenario in roster
    }

    while any(progress.active for progress in progress_by_robot.values()):
        try:
            statuses: Dict[str, str] = flotilla.get_robot_statuses(backend_url)
        except Exception as error:
            logger.warning(f"Failed to retrieve robot statuses, will retry: {error}")
            statuses = {}

        for name, progress in progress_by_robot.items():
            if not progress.active:
                continue
            _observe(progress.context, statuses.get(name))
            _advance(progress)
            if progress.failure is not None:
                logger.error(f"[{name}] failed at {progress.failure}")
            elif not progress.remaining:
                logger.info(f"[{name}] completed all {progress.total} steps")

        if any(progress.active for progress in progress_by_robot.values()):
            time.sleep(POLL_INTERVAL_IN_SECONDS)

    failures: Dict[str, str] = {
        name: progress.failure
        for name, progress in progress_by_robot.items()
        if progress.failure is not None
    }
    if failures:
        summary: str = "\n".join(
            f"  {name}: {failure}" for name, failure in failures.items()
        )
        raise AssertionError(
            f"{len(failures)} of {len(roster)} robots failed:\n{summary}"
        )

    return {name: progress.context for name, progress in progress_by_robot.items()}
