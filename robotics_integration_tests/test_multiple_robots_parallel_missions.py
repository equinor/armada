from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import (
    RobotConfig,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_cannot_interfere_with_running_mission,
)
from robotics_integration_tests.utilities.blob_storage import (
    wait_for_all_mission_blobs,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    schedule_dummy_mission,
    wait_for_all_mission_run_statuses,
    wait_for_all_robot_statuses,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)


def _outcome_matrix_robot(
    name: str, mission_fails: bool = False, return_home_fails: bool = False
) -> RobotConfig:
    return RobotConfig(
        name=name,
        should_fail_normal_task=mission_fails,
        should_fail_return_home=return_home_fails,
    )


def _expected_mission_status(robot: RobotConfig) -> str:
    return "Failed" if robot.should_fail_normal_task else "Successful"


def _expected_robot_status(robot: RobotConfig) -> str:
    return "InterventionNeeded" if robot.should_fail_return_home else "Home"


# Every combination of mission and return-home success and failure.
ROSTER: List[RobotConfig] = [
    _outcome_matrix_robot("MissionOkThenHome"),
    _outcome_matrix_robot("MissionOkThenLost", return_home_fails=True),
    _outcome_matrix_robot("MissionFailThenHome", mission_fails=True),
    _outcome_matrix_robot(
        "MissionFailThenLost", mission_fails=True, return_home_fails=True
    ),
]


def test_robots_play_out_their_missions_without_interference(
    armada_with_robot_roster,
) -> None:
    """Each robot is given one mission and is then left alone."""
    armada: Armada = armada_with_robot_roster(ROSTER)
    backend_url: str = armada.flotilla_backend.backend_url

    mission_runs: Dict[str, Dict] = {
        robot.name: schedule_dummy_mission(backend_url, armada.robots[robot.name])
        for robot in ROSTER
    }

    # The outcomes waited for below prove these had no effect.
    for robot in ROSTER:
        assert_cannot_interfere_with_running_mission(
            armada=armada, robot=armada.robots[robot.name]
        )

    wait_for_all_mission_run_statuses(
        backend_url,
        {
            mission_runs[robot.name]["id"]: _expected_mission_status(robot)
            for robot in ROSTER
        },
    )
    wait_for_all_robot_statuses(
        backend_url,
        {robot.name: _expected_robot_status(robot) for robot in ROSTER},
    )

    _assert_blobs_and_notifications(armada, mission_runs)


def _assert_blobs_and_notifications(
    armada: Armada, mission_runs: Dict[str, Dict]
) -> None:
    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    def expected_blob_count(robot: RobotConfig) -> int:
        if robot.should_fail_normal_task:
            return 0
        return len(mission_runs[robot.name].get("tasks", []))

    # The blob folder path contains the mission run ID, so blobs can be counted
    # per robot although every robot uploads to the same container.
    wait_for_all_mission_blobs(
        container_name=ROSTER[0].plant.installation_code.lower(),
        connection_string=raw_storage_conn,
        mission_blob_expectations={
            mission_runs[robot.name]["id"]: expected_blob_count(robot)
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
