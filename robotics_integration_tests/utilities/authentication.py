"""Access tokens for the integration tests.

Tokens come from the local OAuth2 mock issuer started by the ``oauth_mock``
fixture, not from Azure Entra ID. The suite therefore needs no app registrations,
no tenant and no client secrets.

The mock derives the ``aud`` claim from the requested scope, so asking for
``flotilla-test/.default`` yields a token with ``aud="flotilla-test"`` — which is
what each service is configured to validate against.
"""

from typing import List, Optional

import requests

# Host-side base URL of the mock issuer, published on a random port by
# testcontainers. Set by the `oauth_mock` fixture during setup.
#
# A module-level global is used because the API helpers in
# `flotilla_backend_api.py` and `sara_backend_api.py` build their auth headers
# from plain module functions with no access to pytest fixtures. Each
# pytest-xdist worker is a separate process with its own mock container, so
# there is no cross-worker interference.
_issuer_url: Optional[str] = None


def configure_mock_issuer(host_url: str) -> None:
    """Point token acquisition at a running mock issuer."""
    global _issuer_url
    _issuer_url = host_url


def reset_mock_issuer() -> None:
    """Forget the issuer so a stale URL cannot leak into a later test."""
    global _issuer_url
    _issuer_url = None


def _require_issuer_url() -> str:
    if _issuer_url is None:
        raise RuntimeError(
            "The OAuth2 mock issuer has not been configured. Depend on the "
            "`oauth_mock` fixture, which calls configure_mock_issuer()."
        )
    return _issuer_url


def retrieve_access_token_for_integration_tests_app(resource_client_id: str) -> str:
    """Acquire a token for the given resource via the client credentials flow.

    The signature is unchanged from the previous MSAL implementation so that the
    backend API helpers did not need to be touched.
    """
    response = requests.post(
        f"{_require_issuer_url()}/token",
        data={
            "grant_type": "client_credentials",
            "scope": f"{resource_client_id}/.default",
            "client_id": "integration-tests",
        },
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()
    if "access_token" not in result:
        raise RuntimeError(
            f"Unable to retrieve access token for integration tests app: {result}"
        )
    return result["access_token"]


def issue_access_token(audience: str, roles: List[str]) -> str:
    """Mint a token with an explicit audience and role set.

    Used by the negative authentication tests to prove that authentication is
    genuinely enforced rather than accidentally bypassed.
    """
    response = requests.post(
        f"{_require_issuer_url()}/issue-token",
        json={"audience": audience, "roles": roles},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]
