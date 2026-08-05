"""Assertions that authentication is genuinely enforced.

Kept separate from ``utilities/authentication.py``, which stays concerned only
with minting tokens.

These are deliberately woven into real mission flows rather than run as
standalone tests. Most negative authentication cases are already covered far more
thoroughly, and far more cheaply, by each service's own test suite:

* flotilla enumerates *every* protected endpoint in
  ``api.test/Security/AuthenticationControllerTests.cs``
* sara does the same in ``api.Tests/Security/ProtectedEndpointsTests.cs``
* isar asserts a rejected token in ``tests/isar/apis/security/test_authentication.py``

What none of those can cover is whether authentication is actually switched on in
the deployed configuration, and whether a token minted for one service is
accepted by another. Both need the whole stack running, so they belong here.
"""

from http import HTTPStatus
from typing import Dict, Optional

import requests
from loguru import logger

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.isar import IsarRobot
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication import issue_access_token

_TIMEOUT = 30


def isar_url(robot: IsarRobot, path: str) -> str:
    """Host-reachable URL for one of an ISAR robot's endpoints."""
    port = robot.container.get_exposed_port(robot.port)
    return f"http://localhost:{port}/{path.lstrip('/')}"


def _request(method: str, url: str, token: Optional[str] = None) -> requests.Response:
    headers: Dict[str, str] = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.request(method, url, headers=headers, timeout=_TIMEOUT)


def assert_authentication_is_enforced(url: str, method: str = "GET") -> None:
    """Fail unless an unauthenticated request is rejected.

    Called from the container fixtures so that it holds for every test. A stack
    that has silently come up with authentication disabled would otherwise pass
    the entire suite, since every other assertion is about mission behaviour.
    """
    response = _request(method, url)

    if response.status_code not in (
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    ):
        raise AssertionError(
            f"Authentication is NOT enforced: {method} {url} returned "
            f"{response.status_code} without a token, expected 401 or 403.\n"
            "The stack is running unsecured, which makes every other assertion "
            "in this suite meaningless. Check that the service is running with "
            f"ASPNETCORE_ENVIRONMENT={settings.ASPNETCORE_ENVIRONMENT} (or, for "
            "ISAR, that ISAR_AUTHENTICATION_ENABLED has not been turned off)."
        )

    logger.debug(f"Authentication enforced on {method} {url}")


def assert_token_for_another_service_is_rejected(
    method: str, url: str, audience: str, description: str
) -> None:
    """A correctly signed token for a *different* service must be rejected.

    The token is valid in every respect except its audience, so this exercises
    audience validation rather than signature checking.
    """
    token: str = issue_access_token(audience=audience, roles=["Role.Admin"])
    response = _request(method, url, token=token)

    assert response.status_code == HTTPStatus.UNAUTHORIZED, (
        f"{description}: {method} {url} accepted a token issued for "
        f"'{audience}' and returned {response.status_code}, expected 401. "
        "Services must not accept tokens minted for a different audience."
    )


def assert_missing_role_is_rejected(
    method: str,
    url: str,
    audience: str,
    roles: list[str],
    expected_status: HTTPStatus,
    description: str,
) -> None:
    """A token with the right audience but insufficient roles must be rejected."""
    token: str = issue_access_token(audience=audience, roles=roles)
    response = _request(method, url, token=token)

    assert response.status_code == expected_status, (
        f"{description}: {method} {url} returned {response.status_code} for a "
        f"token with roles {roles}, expected {int(expected_status)}."
    )


def assert_cannot_interfere_with_running_mission(
    armada: Armada, robot: IsarRobot
) -> None:
    """An unauthorised caller must not be able to disturb a running mission.

    Every token here is correctly signed by the same issuer the services trust,
    so a failure means audience or role validation is broken rather than the
    signature chain.

    The caller is expected to go on asserting that the mission reached its
    normal outcome; that is what turns this from an endpoint probe into a
    non-interference test.
    """
    backend_url: str = armada.flotilla_backend.backend_url
    stop_mission_url: str = isar_url(robot, "/schedule/stop-mission")

    # A SARA token must not open Flotilla.
    assert_token_for_another_service_is_rejected(
        method="GET",
        url=f"{backend_url}/robots",
        audience=settings.SARA_AUDIENCE,
        description="Flotilla accepted a SARA token",
    )

    # Correct audience, but a role that grants no access to this installation.
    assert_missing_role_is_rejected(
        method="GET",
        url=f"{backend_url}/robots",
        audience=settings.FLOTILLA_AUDIENCE,
        roles=["Role.User.HUA"],
        expected_status=HTTPStatus.FORBIDDEN,
        description="Flotilla granted access without a sufficient role",
    )

    # A Flotilla token must not let anyone stop the robot directly.
    assert_token_for_another_service_is_rejected(
        method="POST",
        url=stop_mission_url,
        audience=settings.FLOTILLA_AUDIENCE,
        description="ISAR accepted a Flotilla token",
    )

    # Correct audience, but missing ISAR's REQUIRED_ROLE. ISAR answers 401 rather
    # than 403 here: validate_has_role raises fastapi-azure-auth's
    # InvalidAuthHttp, which subclasses UnauthorizedHttp.
    assert_missing_role_is_rejected(
        method="POST",
        url=stop_mission_url,
        audience=settings.ISAR_AUDIENCE,
        roles=["Role.User.HUA"],
        expected_status=HTTPStatus.UNAUTHORIZED,
        description="ISAR accepted a token without Mission.Control",
    )

    logger.info("Unauthorised attempts to interfere with the mission were rejected")


def assert_cannot_pause_mission(armada: Armada, robot: IsarRobot) -> None:
    """An unauthorised caller must not be able to pause a running mission."""
    backend_url: str = armada.flotilla_backend.backend_url
    pause_url: str = f"{backend_url}/robots/{robot.robot_id}/pause"

    assert_token_for_another_service_is_rejected(
        method="POST",
        url=pause_url,
        audience=settings.SARA_AUDIENCE,
        description="Flotilla accepted a SARA token for pause",
    )

    assert_missing_role_is_rejected(
        method="POST",
        url=pause_url,
        audience=settings.FLOTILLA_AUDIENCE,
        roles=["Role.User.HUA"],
        expected_status=HTTPStatus.FORBIDDEN,
        description="Flotilla allowed pause without a sufficient role",
    )

    # Straight at the robot, bypassing Flotilla entirely.
    assert_token_for_another_service_is_rejected(
        method="POST",
        url=isar_url(robot, "/schedule/pause-mission"),
        audience=settings.FLOTILLA_AUDIENCE,
        description="ISAR accepted a Flotilla token for pause",
    )

    logger.info("Unauthorised attempts to pause the mission were rejected")
