"""Access tokens for the integration tests.

Tokens come from the local Keycloak realm started by the ``keycloak`` fixture, not
from Azure Entra ID. The suite therefore needs no app registrations, no tenant and
no client secrets.

Keycloak does not derive the ``aud`` claim from the requested scope the way Entra
does. Each API has a client scope in the realm -- ``isar-api``, ``sara-api``,
``flotilla-api``, ``pointilla-api`` -- carrying a single audience mapper, so asking
for ``flotilla-api`` yields a token with ``aud="flotilla-test"``, which is what
Flotilla is configured to validate against.

Request exactly one such scope per token. Two audience mappers make Keycloak emit
``aud`` as an array, and ISAR's token model accepts only the string form.
"""

from typing import Optional

import requests

from robotics_integration_tests.custom_containers.keycloak import (
    INTEGRATION_TESTS_CLIENT,
    INTEGRATION_TESTS_SECRET,
    LIMITED_ROLE_CLIENT,
    LIMITED_ROLE_SECRET,
    NO_ROLE_CLIENT,
    NO_ROLE_SECRET,
)

# Host-side realm URL, published on a random port by testcontainers. Set by the
# `keycloak` fixture during setup.
#
# A module-level global is used because the API helpers in
# `flotilla_backend_api.py` and `sara_backend_api.py` build their auth headers
# from plain module functions with no access to pytest fixtures. Each
# pytest-xdist worker is a separate process with its own Keycloak container, so
# there is no cross-worker interference.
_issuer_url: Optional[str] = None


def configure_issuer(host_url: str) -> None:
    """Point token acquisition at a running issuer."""
    global _issuer_url
    _issuer_url = host_url


def reset_issuer() -> None:
    """Forget the issuer so a stale URL cannot leak into a later test."""
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
    """Acquire a token for the given API scope, with every role the services need.

    The signature is unchanged from the previous implementations so that the
    backend API helpers did not need to be touched.
    """
    return _request_token(
        scope=scope,
        client_id=INTEGRATION_TESTS_CLIENT,
        client_secret=INTEGRATION_TESTS_SECRET,
    )


def retrieve_access_token_without_roles(scope: str) -> str:
    """Acquire a token with a correct audience but no roles.

    Keycloak has no equivalent of an ad-hoc "issue me a token with these claims"
    endpoint, so a role set is chosen by picking the service account that holds
    it. This one holds none.

    Used by the negative authentication tests to prove that authorisation is
    genuinely enforced rather than accidentally bypassed.
    """
    return _request_token(
        scope=scope,
        client_id=NO_ROLE_CLIENT,
        client_secret=NO_ROLE_SECRET,
    )


def retrieve_access_token_with_insufficient_role(scope: str) -> str:
    """Acquire a token whose roles do not grant access to the endpoint under test.

    Holds Role.User.HUA and nothing else, so Flotilla recognises the principal
    and refuses it with 403, and ISAR refuses it for lacking Mission.Control.
    """
    return _request_token(
        scope=scope,
        client_id=LIMITED_ROLE_CLIENT,
        client_secret=LIMITED_ROLE_SECRET,
    )
