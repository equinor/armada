"""Robot lifecycle situations beyond the ordinary mission.

These cover paths the mission tests never reach: a robot that cannot get home,
and an ISAR that restarts while it still owes Flotilla a mission. Both are
things that genuinely happen in the field, and both are handled by code that
had no coverage.

The MQTT assertions here are deliberately direct. The broker carries the
contract between ISAR and Flotilla, so asserting on the message itself says
something the database state cannot: that ISAR reported the situation, and on
the topic Flotilla is listening to.
"""

from typing import Dict

from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.utilities.flotilla_backend_api import (
    create_mission,
    get_dummy_mission_payload_with_installation,
    schedule_mission,
    wait_for_mission_run_status,
    wait_for_robot_status,
)
from robotics_integration_tests.utilities.teams_notifications import (
    wait_for_all_teams_notifications,
)


def _schedule_dummy_mission(armada: Armada) -> Dict:
    robot_name, robot = next(iter(armada.robots.items()))
    backend_url: str = armada.flotilla_backend.backend_url

    mission: Dict = create_mission(
        backend_url=backend_url,
        payload=get_dummy_mission_payload_with_installation(robot.installation_code),
    )
    mission_run: Dict = schedule_mission(
        backend_url=backend_url,
        robot_id=robot.robot_id,
        mission_id=mission["id"],
    )
    logger.info(f"Scheduled mission run {mission_run['id']} on {robot_name}")
    return mission_run


def test_return_home_retry_exhaustion_needs_intervention(
    armada_with_return_home_failing_robot: Armada,
) -> None:
    """A robot that cannot get home ends up needing a human.

    ISAR retries the return-home mission up to ISAR_RETURN_HOME_RETRY_LIMIT
    times, then gives up and moves to InterventionNeeded. That publishes
    isar/<id>/intervention_needed, which Flotilla turns into a Teams
    notification -- the only way an operator learns a robot is stranded.

    The mission itself must still be reported as successful: the inspections
    were taken and uploaded, and only the trip home failed.
    """
    armada: Armada = armada_with_return_home_failing_robot
    robot_name, _ = next(iter(armada.robots.items()))

    mission_run: Dict = _schedule_dummy_mission(armada)

    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run["id"],
        expected_status="Successful",
    )

    wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="InterventionNeeded",
    )

    # ISAR must say why, on the topic Flotilla subscribes to.
    message = armada.mqtt_recorder.wait_for_message("intervention_needed")
    assert message.payload.get("reason"), (
        f"intervention_needed must carry a reason, got {message.payload}"
    )

    # And the operator must actually be told.
    wait_for_all_teams_notifications(
        receiver=armada.teams_webhook_receiver,
        notification_expectations={robot_name: True},
    )
    notifications = armada.teams_webhook_receiver.get_notification_messages()
    assert any(
        "Intervention needed" in notification for notification in notifications
    ), (
        f"Expected an intervention-needed Teams notification, got {notifications}"
    )


def test_isar_restart_mid_mission_requeues_the_mission(
    armada_with_single_successful_robot: Armada,
) -> None:
    """A mission interrupted by an ISAR restart is re-queued, not lost.

    On startup ISAR publishes isar/<id>/startup. If Flotilla still has a
    current mission for that robot it moves the run back to Queued rather than
    leaving it stuck Ongoing against a robot that has forgotten all about it.
    The run then starts again and completes.
    """
    armada: Armada = armada_with_single_successful_robot
    robot_name, robot = next(iter(armada.robots.items()))

    mission_run: Dict = _schedule_dummy_mission(armada)
    mission_run_id: str = mission_run["id"]

    # Let the mission genuinely start before pulling the rug out.
    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Ongoing",
    )

    armada.mqtt_recorder.clear()
    logger.info(f"Restarting ISAR for robot {robot_name} mid-mission")
    robot.container.get_wrapped_container().restart()

    # The restart is what drives the re-queue, so wait for ISAR to announce it.
    armada.mqtt_recorder.wait_for_message("startup")

    wait_for_mission_run_status(
        backend_url=armada.flotilla_backend.backend_url,
        mission_run_id=mission_run_id,
        expected_status="Successful",
    )

    wait_for_robot_status(
        backend_url=armada.flotilla_backend.backend_url,
        robot_name=robot_name,
        expected_status="Home",
    )
