"""Four ways a mission is brought to a halt, one robot each."""

from typing import List

from robotics_integration_tests.scenarios.steps import (
    RobotScenario,
    Step,
    do,
    latest_mission_is,
    mission_is_under_way_with_tasks_left,
    pause_mission,
    robot_is,
    robot_is_idle_away_from_home,
    schedule_dummy_mission,
    schedule_return_to_home,
    stop_mission,
    wait_for,
    when,
)

TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS = 15.0

# The robot is Available for this long after its positioning mission, which is
# the window for the test to trigger the return home before ISAR does.
RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS = 30
PROMPT_RETURN_HOME_DELAY_SECONDS = 5


def _robot_stopped_by_an_operator(
    name: str, drives_isar_through: str, steps: List[Step]
) -> RobotScenario:
    return RobotScenario(
        name=name,
        drives_isar_through=drives_isar_through,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        return_home_delay_in_seconds=PROMPT_RETURN_HOME_DELAY_SECONDS,
        steps=steps,
    )


# ISAR does not let an operator stop a return home. Scheduling a mission
# supersedes it instead.
def _robot_whose_return_home_is_superseded_by_a_mission(
    name: str, drives_isar_through: str, steps: List[Step]
) -> RobotScenario:
    return RobotScenario(
        name=name,
        drives_isar_through=drives_isar_through,
        task_duration_in_seconds=TASK_DURATION_THAT_LEAVES_TIME_TO_INTERFERE_SECONDS,
        return_home_delay_in_seconds=RETURN_HOME_DELAY_THAT_LETS_THE_TEST_GO_FIRST_SECONDS,
        steps=steps,
    )


# A robot that is already home completes a return home instantly, leaving
# nothing to pause or supersede.
def _leave_home_then_start_returning() -> List[Step]:
    return [
        do(schedule_dummy_mission),
        wait_for(latest_mission_is("Successful")),
        when(robot_is_idle_away_from_home, schedule_return_to_home),
    ]


ROSTER = [
    _robot_stopped_by_an_operator(
        name="StopDuringMission",
        drives_isar_through="Monitor -> Stopping -> AwaitNextMission",
        steps=[
            do(schedule_dummy_mission),
            when(mission_is_under_way_with_tasks_left, stop_mission),
            wait_for(latest_mission_is("Cancelled")),
            wait_for(robot_is("Home")),
        ],
    ),
    _robot_stopped_by_an_operator(
        name="StopWhilePaused",
        drives_isar_through=(
            "Monitor -> Pausing -> Paused -> StoppingPausedMission -> AwaitNextMission"
        ),
        steps=[
            do(schedule_dummy_mission),
            when(mission_is_under_way_with_tasks_left, pause_mission),
            when(robot_is("Paused"), stop_mission),
            wait_for(latest_mission_is("Cancelled")),
            wait_for(robot_is("Home")),
        ],
    ),
    _robot_whose_return_home_is_superseded_by_a_mission(
        name="MissionWhileReturningHome",
        drives_isar_through="ReturningHome -> StoppingReturnHome -> Monitor",
        steps=[
            *_leave_home_then_start_returning(),
            when(robot_is("ReturningHome"), schedule_dummy_mission),
            wait_for(latest_mission_is("Successful")),
            wait_for(robot_is("Home")),
        ],
    ),
    _robot_whose_return_home_is_superseded_by_a_mission(
        name="MissionWhileReturnHomePaused",
        drives_isar_through=(
            "ReturningHome -> PausingReturnHome -> ReturnHomePaused -> "
            "StoppingPausedReturnHome -> Monitor"
        ),
        steps=[
            *_leave_home_then_start_returning(),
            when(robot_is("ReturningHome"), pause_mission),
            when(robot_is("ReturnHomePaused"), schedule_dummy_mission),
            wait_for(latest_mission_is("Successful")),
            wait_for(robot_is("Home")),
        ],
    ),
]
