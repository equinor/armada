"""Every combination of mission and return-home success and failure."""

from robotics_integration_tests.scenarios.failure_notes import (
    naming_the_robot_of_each_mission_run,
)
from robotics_integration_tests.scenarios.fleet import Fleet, RobotScenario
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)


def _robot(
    name: str, mission_fails: bool = False, return_home_fails: bool = False
) -> RobotScenario:
    return RobotScenario(
        name=name,
        should_fail_normal_task=mission_fails,
        should_fail_return_home=return_home_fails,
        expected_mission_status="Failed" if mission_fails else "Successful",
        expected_robot_status="InterventionNeeded" if return_home_fails else "Home",
    )


ROSTER = [
    _robot("MissionOkThenHome"),
    _robot("MissionOkThenLost", return_home_fails=True),
    _robot("MissionFailThenHome", mission_fails=True),
    _robot("MissionFailThenLost", mission_fails=True, return_home_fails=True),
]


def assert_blobs_and_notifications(fleet: Fleet) -> None:
    armada = fleet.armada
    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    def expected_blob_count(robot: RobotScenario) -> int:
        if robot.should_fail_normal_task:
            return 0
        return len(fleet.mission_runs[robot.name][0].get("tasks", []))

    # The blob folder path contains the mission run ID, so blobs can be counted
    # per robot although every robot uploads to the same container.
    with naming_the_robot_of_each_mission_run(
        {fleet.mission_runs[robot.name][0]["id"]: robot.name for robot in ROSTER}
    ):
        wait_for_all_mission_blobs(
            container_name=ROSTER[0].plant.installation_code.lower(),
            connection_string=raw_storage_conn,
            mission_blob_expectations={
                fleet.mission_runs[robot.name][0]["id"]: expected_blob_count(robot)
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
