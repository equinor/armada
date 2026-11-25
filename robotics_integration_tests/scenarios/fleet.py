"""A roster of robots: what a test does to them and what it waits for in between."""

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    IsarRobot,
    Plant,
    RobotConfig,
)
from robotics_integration_tests.utilities import flotilla_backend_api as flotilla

POLL_INTERVAL_IN_SECONDS: float = 1.0
DEFAULT_TIMEOUT_IN_SECONDS: float = 240.0

# Robots that a test acts on in the same window share this, so that waiting for
# all of them cannot outlast the window of one.
TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS: float = 15.0

POLLABLE_ROBOT_STATUSES = frozenset(
    {
        # A robot rests in these until something acts on it.
        "Home",
        "Paused",
        "ReturnHomePaused",
        "Lockdown",
        "Maintenance",
        "InterventionNeeded",
        # These last for several polls.
        "Available",  # for the return-home delay
        "ReturningHome",  # for the return-home mission
        "Recharging",  # until the battery is charged
        "RechargingWithMission",
    }
)


@dataclass
class RobotScenario(RobotConfig):
    """One robot in a multi-robot test: its configuration and how it must end up."""

    should_start_at_home: bool = True
    return_home_retry_limit: int = 1
    # Robots discharge while away from home, and a long test can drift past
    # ISAR's default 25 % and divert into recharging. Scenarios that are about
    # battery set their own threshold.
    mission_battery_start_threshold: float = 0.0
    # Of the robot's latest mission run. None for a robot that is given none.
    expected_mission_status: Optional[str] = "Successful"
    expected_robot_status: str = "Home"


@dataclass(frozen=True)
class Condition:
    robot_name: str
    description: str
    is_met: Callable[["Fleet"], bool]


def require_status_that_lasts_for_several_polls(status: str) -> None:
    if status not in POLLABLE_ROBOT_STATUSES:
        raise ValueError(
            f"'{status}' can pass between two polls of Flotilla. Wait for the "
            f"mission run status it leads to instead, or for one of "
            f"{sorted(POLLABLE_ROBOT_STATUSES)}."
        )


def robot_is(robot_name: str, expected_status: str) -> Condition:
    require_status_that_lasts_for_several_polls(expected_status)
    return Condition(
        robot_name,
        f"robot is {expected_status}",
        lambda fleet: fleet.statuses.get(robot_name) == expected_status,
    )


def robot_has_been(robot_name: str, status: str) -> Condition:
    """Met by a status the robot was seen in at any poll since the fleet was created."""
    require_status_that_lasts_for_several_polls(status)
    return Condition(
        robot_name,
        f"robot has been {status}",
        lambda fleet: status in fleet.statuses_seen[robot_name],
    )


def latest_mission_is(robot_name: str, expected_status: str) -> Condition:
    return Condition(
        robot_name,
        f"latest mission is {expected_status}",
        lambda fleet: fleet.latest_mission_run(robot_name).get("status")
        == expected_status,
    )


def mission_is_under_way_with_tasks_left(robot_name: str) -> Condition:
    return Condition(
        robot_name,
        "second task of latest mission is InProgress",
        lambda fleet: fleet.latest_mission_run(robot_name)["tasks"][1].get("status")
        == "InProgress",
    )


class Fleet:
    """The robots of one test.

    Every wait polls all robots, so ``statuses_seen`` has no gaps other than the
    time the test spends between waits.
    """

    def __init__(self, armada: Armada, roster: List[RobotScenario]) -> None:
        self.armada: Armada = armada
        self.roster: List[RobotScenario] = roster
        self.backend_url: str = armada.flotilla_backend.backend_url
        # Each robot's status in Flotilla as of the latest poll.
        self.statuses: Dict[str, str] = {}
        # Each distinct status a robot was seen in, in order.
        self.statuses_seen: Dict[str, List[str]] = {robot.name: [] for robot in roster}
        # Every mission run scheduled on a robot, oldest first.
        self.mission_runs: Dict[str, List[Dict]] = {robot.name: [] for robot in roster}

    def robot(self, robot_name: str) -> IsarRobot:
        return self.armada.robots[robot_name]

    def schedule_dummy_mission(self, *robot_names: str) -> None:
        for robot_name in robot_names:
            robot: IsarRobot = self.robot(robot_name)
            self.mission_runs[robot_name].append(
                flotilla.schedule_dummy_mission(
                    backend_url=self.backend_url,
                    robot_id=robot.robot_id,
                    installation_code=robot.installation_code,
                )
            )

    def pause_mission(self, robot_name: str) -> None:
        flotilla.pause_mission(self.backend_url, self.robot(robot_name).robot_id)

    def stop_mission(self, robot_name: str) -> None:
        flotilla.stop_mission(self.backend_url, self.robot(robot_name).robot_id)

    def set_maintenance_mode(self, robot_name: str) -> None:
        flotilla.set_maintenance_mode(self.backend_url, self.robot(robot_name).robot_id)

    def release_maintenance_mode(self, robot_name: str) -> None:
        flotilla.release_maintenance_mode(
            self.backend_url, self.robot(robot_name).robot_id
        )

    def send_all_robots_to_lockdown(self, plant: Plant) -> None:
        flotilla.send_all_robots_to_lockdown(self.backend_url, plant.installation_code)

    def clear_emergency_state(self, plant: Plant) -> None:
        flotilla.clear_emergency_state(self.backend_url, plant.installation_code)

    def latest_mission_run(self, robot_name: str) -> Dict:
        return flotilla.get_mission_run_by_id(
            backend_url=self.backend_url,
            mission_run_id=self.mission_runs[robot_name][-1]["id"],
        )

    def expected_outcomes(
        self, roster: Optional[List[RobotScenario]] = None
    ) -> List[Condition]:
        """Of every robot, or of the robots in *roster*."""
        outcomes: List[Condition] = []
        for robot in self.roster if roster is None else roster:
            if robot.expected_mission_status is not None:
                outcomes.append(
                    latest_mission_is(robot.name, robot.expected_mission_status)
                )
            outcomes.append(robot_is(robot.name, robot.expected_robot_status))
        return outcomes

    def wait_until(
        self,
        *conditions: Condition,
        timeout_in_seconds: float = DEFAULT_TIMEOUT_IN_SECONDS,
    ) -> None:
        """Poll until every condition holds in the same poll.

        On timeout the failure names every condition that is still unmet.
        """
        started: float = time.monotonic()
        while True:
            self._poll_robot_statuses()
            unmet: Dict[Condition, str] = {}
            for condition in conditions:
                try:
                    if not condition.is_met(self):
                        unmet[condition] = ""
                except Exception as error:
                    unmet[condition] = f" Could not be checked: {error!r}."

            if not unmet:
                for condition in conditions:
                    logger.info(f"[{condition.robot_name}] {condition.description}")
                return

            if time.monotonic() - started > timeout_in_seconds:
                summary: str = "\n".join(
                    f"  {condition.robot_name}: '{condition.description}' was not "
                    f"met.{error} Statuses seen: "
                    f"{self.statuses_seen[condition.robot_name]}"
                    for condition, error in unmet.items()
                )
                raise AssertionError(
                    f"{len(unmet)} of {len(conditions)} conditions were not met "
                    f"together within {timeout_in_seconds:g}s:\n{summary}"
                )
            time.sleep(POLL_INTERVAL_IN_SECONDS)

    def _poll_robot_statuses(self) -> None:
        try:
            self.statuses = flotilla.get_robot_statuses(self.backend_url)
        except Exception as error:
            logger.warning(f"Failed to retrieve robot statuses, will retry: {error}")
            self.statuses = {}
            return
        for robot_name, seen in self.statuses_seen.items():
            status: Optional[str] = self.statuses.get(robot_name)
            if status is not None and (not seen or seen[-1] != status):
                seen.append(status)
                logger.info(f"[{robot_name}] is in status '{status}'")
