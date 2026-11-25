from typing import List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios import outcome_matrix, recharging
from robotics_integration_tests.scenarios.fleet import (
    Fleet,
    RobotScenario,
    robot_has_been,
)
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_interfere_with_running_mission,
)

ROSTER: List[RobotScenario] = [*outcome_matrix.ROSTER, *recharging.ROSTER]


def test_robots_play_out_their_missions_without_interference(
    armada_with_robot_roster,
) -> None:
    """Each robot is given one mission and is then left alone."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    fleet = Fleet(armada, ROSTER)

    fleet.schedule_dummy_mission(*(robot.name for robot in ROSTER))

    # The outcomes waited for below prove these had no effect.
    for robot in ROSTER:
        assert_cannot_interfere_with_running_mission(
            armada=armada, robot=fleet.robot(robot.name)
        )

    fleet.wait_until(
        *fleet.expected_outcomes(),
        robot_has_been(recharging.LOW_BATTERY_WHILE_IDLE, "Recharging"),
        # Only reachable when the stop handed the mission back as an
        # AbortedMission (equinor/isar#1176).
        robot_has_been(recharging.LOW_BATTERY_DURING_MISSION, "RechargingWithMission"),
        timeout_in_seconds=recharging.TIMEOUT_FOR_BATTERY_TO_RUN_DOWN_AND_RECHARGE_SECONDS,
    )

    outcome_matrix.assert_blobs_and_notifications(fleet)
