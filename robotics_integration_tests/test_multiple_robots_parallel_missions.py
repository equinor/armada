from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios import (
    maintenance,
    outcome_matrix,
    recharging,
    stopping,
)
from robotics_integration_tests.scenarios.steps import (
    RobotContext,
    RobotScenario,
    advance_each_robot_through_its_own_steps,
)

ROSTER: List[RobotScenario] = [
    *outcome_matrix.ROSTER,
    *stopping.ROSTER,
    *maintenance.ROSTER,
    *recharging.ROSTER,
]


def test_multiple_robots_in_parallel(armada_with_robot_roster) -> None:
    armada: Armada = armada_with_robot_roster(ROSTER)

    contexts: Dict[str, RobotContext] = advance_each_robot_through_its_own_steps(
        armada=armada, roster=ROSTER
    )

    outcome_matrix.assert_blobs_and_notifications(armada=armada, contexts=contexts)
