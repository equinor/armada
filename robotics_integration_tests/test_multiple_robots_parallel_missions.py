from collections import Counter
from types import ModuleType
from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.scenarios import (
    maintenance,
    outcome_matrix,
    recharging,
    stopping,
)
from robotics_integration_tests.scenarios.steps import (
    RobotContext,
    advance_each_robot_through_its_own_steps,
)

# An armada is about twelve containers before any robot is added, so every
# group's robots share one.
SCENARIO_GROUPS_SHARING_ONE_ARMADA: List[ModuleType] = [
    outcome_matrix,
    stopping,
    maintenance,
    recharging,
]


def _assert_robot_names_and_aliases_are_unique(roster: List[RobotScenario]) -> None:
    for attribute in ("name", "alias"):
        duplicates = [
            value
            for value, count in Counter(getattr(s, attribute) for s in roster).items()
            if count > 1
        ]
        assert not duplicates, f"Duplicate robot {attribute}s: {duplicates}"


def _assert_no_robot_name_contains_another(roster: List[RobotScenario]) -> None:
    names = [scenario.name for scenario in roster]
    overlapping = [(a, b) for a in names for b in names if a != b and a in b]
    assert not overlapping, (
        f"Teams notifications are matched to a robot by substring, but these "
        f"names are contained in other names: {overlapping}"
    )


def _robots_of_every_scenario_group() -> List[RobotScenario]:
    roster: List[RobotScenario] = [
        scenario
        for group in SCENARIO_GROUPS_SHARING_ONE_ARMADA
        for scenario in group.ROSTER
    ]
    _assert_robot_names_and_aliases_are_unique(roster)
    _assert_no_robot_name_contains_another(roster)
    return roster


def test_multiple_robots_in_parallel(armada_with_robot_roster) -> None:
    roster: List[RobotScenario] = _robots_of_every_scenario_group()
    armada: Armada = armada_with_robot_roster(roster)

    contexts: Dict[str, RobotContext] = advance_each_robot_through_its_own_steps(
        armada=armada, roster=roster
    )

    outcome_matrix.assert_blobs_and_notifications(armada=armada, contexts=contexts)
