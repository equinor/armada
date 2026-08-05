"""Access tokens for the integration tests, minted by the local Keycloak realm.

Unlike Entra, Keycloak does not derive ``aud`` from the requested scope: each API
has a client scope carrying a single audience mapper. Request exactly one per
token -- two make Keycloak emit ``aud`` as an array, which ISAR rejects.
"""

from typing import Optional

import requests

from robotics_integration_tests.custom_containers.keycloak import (
    INTEGRATION_TESTS_CLIENT,
    INTEGRATION_TESTS_SECRET,
    LIMITED_ROLE_CLIENT,
    LIMITED_ROLE_SECRET,
)

# Set by the `keycloak` fixture. A global because the API helpers build their auth
# headers from plain module functions with no access to fixtures; each xdist worker
# is a separate process with its own container.
_issuer_url: Optional[str] = None


def configure_issuer(host_url: str) -> None:
    global _issuer_url
    _issuer_url = host_url


def reset_issuer() -> None:
    global _issuer_url
    _issuer_url = None


def _require_issuer_url() -> str:
    if _issuer_url is None:
        raise RuntimeError(
            "The issuer has not been configured. Depend on the `keycloak` "
            "fixture, which calls configure_issuer()."
        )
    return _issuer_url


def _request_token(scope: str, client_id: str, client_secret: str) -> str:
    response = requests.post(
        f"{_require_issuer_url()}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "scope": scope,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()
    if "access_token" not in result:
        raise RuntimeError(f"Unable to retrieve access token for {scope}: {result}")
    return result["access_token"]


def retrieve_access_token_for_integration_tests_app(scope: str) -> str:
    return _request_token(
        scope=scope,
        client_id=INTEGRATION_TESTS_CLIENT,
        client_secret=INTEGRATION_TESTS_SECRET,
    )


def retrieve_access_token_with_insufficient_role(scope: str) -> str:
    """Acquire a token whose roles do not grant access to the endpoint under test.

    Flotilla recognises the principal and refuses it with 403; ISAR refuses it for
    lacking Mission.Control.
    """
    return _request_token(
        scope=scope,
        client_id=LIMITED_ROLE_CLIENT,
        client_secret=LIMITED_ROLE_SECRET,
    )
