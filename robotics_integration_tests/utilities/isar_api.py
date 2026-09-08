"""Authenticated calls straight to an ISAR robot's own API.

Most scenarios are driven through Flotilla, because that is how an operator
actually reaches a robot. Lockdown is the exception: Flotilla's emergency action
currently subscribes both its lockdown and its release handler to the same
``RobotEmergencyEventArgs`` event, and neither inspects the message that is meant
to tell them apart, so every emergency call sends ISAR *both* a lockdown and a
release. Releasing an installation therefore frees the robots and immediately
locks them again.

Until that is fixed in flotilla, lockdown coverage has to talk to ISAR directly.
The states under test belong to ISAR either way, so nothing is lost but the
Flotilla round trip.
"""

import requests
from loguru import logger
from requests import Response

from robotics_integration_tests.custom_containers.isar import IsarRobot
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication import (
    retrieve_access_token_for_integration_tests_app,
)
from robotics_integration_tests.utilities.authentication_assertions import isar_url

_TIMEOUT = 30


def _post(robot: IsarRobot, path: str, description: str) -> None:
    token: str = retrieve_access_token_for_integration_tests_app(settings.ISAR_SCOPE)
    url: str = isar_url(robot, path)

    response: Response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )

    if not response.ok:
        raise AssertionError(
            f"{description} failed: POST {url} returned {response.status_code}\n"
            f"Response body:\n{response.text}"
        )

    logger.info(f"{description} succeeded")


def send_to_lockdown(robot: IsarRobot) -> None:
    _post(robot, "/schedule/lockdown", f"Sending {robot.name} to lockdown")


def release_from_lockdown(robot: IsarRobot) -> None:
    _post(
        robot, "/schedule/release-lockdown", f"Releasing {robot.name} from lockdown"
    )
