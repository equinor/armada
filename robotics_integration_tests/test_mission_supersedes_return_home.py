from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios.fleet import Fleet, robot_is
from robotics_integration_tests.scenarios.superseding_return_home import (
    MISSION_WHILE_RETURN_HOME_PAUSED,
    MISSION_WHILE_RETURNING_HOME,
    ROSTER,
)


def test_new_mission_supersedes_a_running_and_a_paused_return_home(
    armada_with_robot_roster,
) -> None:
    """ISAR does not let an operator stop a return home. A new mission
    supersedes it instead.

    The comment on an action is the ISAR states it drives the robot through.
    """
    armada: Armada = armada_with_robot_roster(ROSTER)
    fleet = Fleet(armada, ROSTER)

    # ISAR starts the return home itself once the return-home delay has passed
    # after a mission. A robot that is already home has nothing to return
    # from, which is why these two are given a mission first.
    fleet.schedule_dummy_mission(
        MISSION_WHILE_RETURNING_HOME, MISSION_WHILE_RETURN_HOME_PAUSED
    )

    fleet.wait_until(
        robot_is(MISSION_WHILE_RETURNING_HOME, "ReturningHome"),
        robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturningHome"),
    )
    # ReturningHome -> StoppingReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURNING_HOME)
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused
    fleet.pause_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    fleet.wait_until(robot_is(MISSION_WHILE_RETURN_HOME_PAUSED, "ReturnHomePaused"))
    # ReturnHomePaused -> StoppingPausedReturnHome -> Monitor
    fleet.schedule_dummy_mission(MISSION_WHILE_RETURN_HOME_PAUSED)

    fleet.wait_until(*fleet.expected_outcomes())
