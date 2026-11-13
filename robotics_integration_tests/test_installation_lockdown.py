from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios import lockdown


def test_lockdown_affects_only_the_plant_it_is_triggered_on(
    armada_with_robot_roster,
) -> None:
    armada: Armada = armada_with_robot_roster(lockdown.ROSTER)

    lockdown.lock_down_one_plant_and_verify_the_other_carries_on(armada)
