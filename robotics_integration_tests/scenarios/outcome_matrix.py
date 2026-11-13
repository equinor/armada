"""Every combination of mission and return-home success and failure."""

from typing import Dict, List

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import RobotScenario
from robotics_integration_tests.scenarios.steps import (
    RobotContext,
    Step,
    immediately,
    mission_status,
    robot_status,
    schedule_dummy_mission,
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

ROBOT_EXPECTATIONS: Dict[str, Dict] = {
    "MissionOkThenHome": {
        "mission_status": "Successful",
        "robot_status": "Home",
        "expect_blobs": True,
    },
    "MissionOkThenLost": {
        "mission_status": "Successful",
        "robot_status": "InterventionNeeded",
        "expect_blobs": True,
    },
    "MissionFailThenHome": {
        "mission_status": "Failed",
        "robot_status": "Home",
        "expect_blobs": False,
    },
    "MissionFailThenLost": {
        "mission_status": "Failed",
        "robot_status": "InterventionNeeded",
        "expect_blobs": False,
    },
}


def attempt_unauthorised_interference(context: RobotContext) -> None:
    assert_cannot_interfere_with_running_mission(
        armada=context.armada, robot=context.robot
    )


def _outcome_steps(name: str) -> List[Step]:
    expectations: Dict = ROBOT_EXPECTATIONS[name]
    return [
        Step(immediately, then=schedule_dummy_mission),
        Step(mission_status(expectations["mission_status"])),
        Step(robot_status(expectations["robot_status"])),
    ]


ROSTER = [
    RobotScenario(
        name="MissionOkThenHome",
        alias="isar_mission_ok_then_home",
        steps=[
            Step(immediately, then=schedule_dummy_mission),
            # The mission is now in flight. Its outcome below proves the
            # unauthorised calls had no effect.
            Step(immediately, then=attempt_unauthorised_interference),
            *_outcome_steps("MissionOkThenHome")[1:],
        ],
    ),
    RobotScenario(
        name="MissionOkThenLost",
        alias="isar_mission_ok_then_lost",
        should_fail_return_home=True,
        steps=_outcome_steps("MissionOkThenLost"),
    ),
    RobotScenario(
        name="MissionFailThenHome",
        alias="isar_mission_fail_then_home",
        should_fail_normal_task=True,
        steps=_outcome_steps("MissionFailThenHome"),
    ),
    RobotScenario(
        name="MissionFailThenLost",
        alias="isar_mission_fail_then_lost",
        should_fail_normal_task=True,
        should_fail_return_home=True,
        steps=_outcome_steps("MissionFailThenLost"),
    ),
]


def assert_blobs_and_notifications(
    armada: Armada, contexts: Dict[str, RobotContext]
) -> None:
    mission_runs: Dict[str, Dict] = {
        name: contexts[name].mission_runs[0] for name in ROBOT_EXPECTATIONS
    }

    raw_storage_conn: str = armada.armada_storage.azurite_containers.get(
        settings.SARA_RAW_STORAGE_CONTAINER
    ).host_connection_string

    # All robots share the same installation and blob container. The blob
    # folder path contains the mission run ID, so blob counts can be checked per
    # robot: successful missions should have blobs and failed ones should not.
    blob_container_name: str = armada.robots[
        "MissionOkThenHome"
    ].installation_code.lower()

    wait_for_all_mission_blobs(
        container_name=blob_container_name,
        connection_string=raw_storage_conn,
        mission_blob_expectations={
            mission_runs[name]["id"]: (
                len(mission_runs[name].get("tasks", [])) if exp["expect_blobs"] else 0
            )
            for name, exp in ROBOT_EXPECTATIONS.items()
        },
    )

    receiver = armada.teams_webhook_receiver
    assert receiver is not None, "Teams webhook receiver was not started"

    wait_for_all_teams_notifications(
        receiver=receiver,
        notification_expectations={
            name: exp["robot_status"] == "InterventionNeeded"
            for name, exp in ROBOT_EXPECTATIONS.items()
        },
    )
