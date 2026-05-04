import time
from datetime import datetime, timedelta
from typing import Dict, List

from loguru import logger

from robotics_integration_tests.custom_containers.teams_webhook_receiver import (
    TeamsWebhookReceiver,
)


def wait_for_all_teams_notifications(
    receiver: TeamsWebhookReceiver,
    notification_expectations: Dict[str, bool],
    timeout: int = 60,
) -> None:
    """Poll the webhook receiver until all expected notifications have arrived,
    or *timeout* seconds have elapsed.

    *notification_expectations* maps robot names to whether a notification is
    expected (``True``) or not (``False``).

    Robots expecting notifications are polled in a loop. Once all expected
    notifications have arrived, robots that should **not** have notifications
    are verified to have none.
    """
    expected: List[str] = [
        name for name, should_notify in notification_expectations.items() if should_notify
    ]
    not_expected: List[str] = [
        name for name, should_notify in notification_expectations.items() if not should_notify
    ]

    remaining: set = set(expected)
    start_time: datetime = datetime.now()

    while remaining:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            messages = receiver.get_notification_messages()
            raise TimeoutError(
                f"Timeout waiting for Teams notifications within {timeout}s. "
                f"Still waiting for robots: {remaining}. "
                f"Received messages: {messages}"
            )

        messages = receiver.get_notification_messages()
        for robot_name in list(remaining):
            matching = [m for m in messages if robot_name in m]
            if matching:
                logger.info(
                    f"Received Teams notification for robot '{robot_name}': {matching[0]}"
                )
                remaining.discard(robot_name)

        if remaining:
            time.sleep(1)

    messages = receiver.get_notification_messages()
    logger.info(f"All expected notifications received. Total messages: {messages}")

    for robot_name in not_expected:
        matching = [m for m in messages if robot_name in m]
        if matching:
            raise AssertionError(
                f"Robot '{robot_name}' should not have a Teams notification "
                f"but received: {matching}"
            )
        logger.info(f"Robot '{robot_name}' correctly has no Teams notification")
