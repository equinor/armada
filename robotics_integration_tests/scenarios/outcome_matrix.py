"""Every combination of mission and return-home success and failure."""

from typing import Dict, Sequence

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.scenarios.steps import (
    RobotContext,
    RobotScenario,
    Step,
    do,
    latest_mission_is,
    robot_is,
    schedule_dummy_mission,
    wait_for,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_interfere_with_running_mission,
)
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)


def attempt_unauthorised_interference(context: RobotContext) -> None:
    assert_cannot_interfere_with_running_mission(
        armada=context.armada, robot=context.robot
    )


def _robot(
    name: str,
    mission_fails: bool = False,
    return_home_fails: bool = False,
    while_the_mission_is_in_flight: Sequence[Step] = (),
) -> RobotScenario:
    return RobotScenario(
        name=name,
        should_fail_normal_task=mission_fails,
        should_fail_return_home=return_home_fails,
        steps=[
            do(schedule_dummy_mission),
            *while_the_mission_is_in_flight,
            wait_for(latest_mission_is("Failed" if mission_fails else "Successful")),
            wait_for(robot_is("InterventionNeeded" if return_home_fails else "Home")),
        ],
    )


ROSTER = [
    _robot(
        "MissionOkThenHome",
        while_the_mission_is_in_flight=[do(attempt_unauthorised_interference)],
    ),
    _robot("MissionOkThenLost", return_home_fails=True),
    _robot("MissionFailThenHome", mission_fails=True),
    _robot("MissionFailThenLost", mission_fails=True, return_home_fails=True),
]


def assert_blobs_and_notifications(
    armada: Armada, contexts: Dict[str, RobotContext]
) -> None:
    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    def expected_blob_count(robot: RobotScenario) -> int:
        if robot.should_fail_normal_task:
            return 0
        return len(contexts[robot.name].mission_runs[0].get("tasks", []))

    # The blob folder path contains the mission run ID, so blobs can be counted
    # per robot although every robot uploads to the same container.
    wait_for_all_mission_blobs(
        container_name=ROSTER[0].plant.blob_container,
        connection_string=raw_storage_conn,
        mission_blob_expectations={
            contexts[robot.name].mission_runs[0]["id"]: expected_blob_count(robot)
            for robot in ROSTER
        },
    )

    receiver = armada.teams_webhook_receiver
    assert receiver is not None, "Teams webhook receiver was not started"

    wait_for_all_teams_notifications(
        receiver=receiver,
        notification_expectations={
            robot.name: robot.should_fail_return_home for robot in ROSTER
        },
    )
