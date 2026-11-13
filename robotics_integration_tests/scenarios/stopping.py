"""Four ways a mission is brought to a halt, one robot each."""

from typing import List

from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.scenarios.steps import (
    Step,
    immediately,
    mission_is_under_way_with_tasks_left,
    mission_status,
    pause_mission,
    robot_is_idle_away_from_home,
    robot_status,
    schedule_dummy_mission,
    schedule_return_to_home,
    stop_mission,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 15.0

# The robot is Available for this long after its positioning mission, which is
# the window for the test to trigger the return home before ISAR does.
RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS = 30
PROMPT_RETURN_HOME_DELAY_SECONDS = 5


def _robot_stopped_by_an_operator(
    name: str, alias: str, steps: List[Step]
) -> RobotScenario:
    return RobotScenario(
        name=name,
        alias=alias,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        return_home_delay_in_seconds=PROMPT_RETURN_HOME_DELAY_SECONDS,
        steps=steps,
    )


def _robot_whose_return_home_is_superseded(
    name: str, alias: str, steps: List[Step]
) -> RobotScenario:
    return RobotScenario(
        name=name,
        alias=alias,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        return_home_delay_in_seconds=RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS,
        steps=steps,
    )


def _leave_home_then_start_returning() -> List[Step]:
    # A robot that is already home completes a return home instantly, leaving
    # nothing to pause or supersede.
    return [
        Step(immediately, then=schedule_dummy_mission),
        Step(mission_status("Successful")),
        Step(robot_is_idle_away_from_home, then=schedule_return_to_home),
    ]


ROSTER = [
    # Monitor -> Stopping -> AwaitNextMission
    _robot_stopped_by_an_operator(
        name="StopDuringMission",
        alias="isar_stop_during_mission",
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            Step(mission_is_under_way_with_tasks_left, then=stop_mission),
            Step(mission_status("Cancelled")),
            Step(robot_status("Home")),
        ],
    ),
    # Monitor -> Pausing -> Paused -> StoppingPausedMission -> AwaitNextMission
    _robot_stopped_by_an_operator(
        name="StopWhilePaused",
        alias="isar_stop_while_paused",
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            Step(mission_is_under_way_with_tasks_left, then=pause_mission),
            Step(robot_status("Paused"), then=stop_mission),
            Step(mission_status("Cancelled")),
            Step(robot_status("Home")),
        ],
    ),
    # ISAR does not let an operator stop a return home. Scheduling a mission
    # supersedes it instead: ReturningHome -> StoppingReturnHome -> Monitor
    _robot_whose_return_home_is_superseded(
        name="MissionWhileReturningHome",
        alias="isar_mission_while_returning_home",
        steps=[
            *_leave_home_then_start_returning(),
            Step(robot_status("ReturningHome"), then=schedule_dummy_mission),
            Step(mission_status("Successful")),
            Step(robot_status("Home")),
        ],
    ),
    # ReturningHome -> PausingReturnHome -> ReturnHomePaused ->
    # StoppingPausedReturnHome -> Monitor
    _robot_whose_return_home_is_superseded(
        name="MissionWhileReturnHomePaused",
        alias="isar_mission_while_return_home_paused",
        steps=[
            *_leave_home_then_start_returning(),
            Step(robot_status("ReturningHome"), then=pause_mission),
            Step(robot_status("ReturnHomePaused"), then=schedule_dummy_mission),
            Step(mission_status("Successful")),
            Step(robot_status("Home")),
        ],
    ),
]
