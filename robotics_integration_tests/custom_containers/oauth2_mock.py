import time
from pathlib import Path

import requests
from docker.models.networks import Network
from robotics_integration_tests.custom_containers.image_builder import build_image_once
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)

_IMAGE_DIR = Path(__file__).resolve().parent.parent / "custom_images" / "oauth2_mock"


class OAuth2Mock:
    """Local OpenID Connect issuer replacing Azure Entra ID for the test run.

    Services reach it on the Docker network under ``alias``; the pytest process
    reaches it on the published host port. Tokens carry the *in-network* issuer
    either way, which is what the services validate against.
    """

    def __init__(
        self,
        container: StreamLoggingDockerContainer,
        port: int,
        alias: str,
    ) -> None:
        self.container = container
        self.port = port
        self.alias = alias

    @property
    def internal_url(self) -> str:
        """Issuer URL as seen by other containers on the same Docker network."""
        return f"http://{self.alias}:{self.port}"

    @property
    def internal_openid_config_url(self) -> str:
        """Discovery document URL to hand to the services."""
        return f"{self.internal_url}/.well-known/openid-configuration"

    @property
    def host_url(self) -> str:
        """URL reachable from the test host."""
        return f"http://localhost:{self.container.get_exposed_port(self.port)}"

    def wait_until_ready(self, timeout: int = 60) -> None:
        """Block until the discovery document is served."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = requests.get(
                    f"{self.host_url}/.well-known/openid-configuration", timeout=5
                )
                if response.ok:
                    return
            except requests.RequestException as error:  # pragma: no cover - timing
                last_error = error
            time.sleep(0.5)
        raise TimeoutError(
            f"oauth2 mock did not become ready within {timeout}s: {last_error}"
        )

    def get_token(self, resource_client_id: str) -> str:
        """Mint a token via the standard client-credentials flow.

        The audience is derived from the requested scope by the mock, so this
        mirrors what the services themselves do.
        """
        response = requests.post(
            f"{self.host_url}/token",
            data={
                "grant_type": "client_credentials",
                "scope": f"{resource_client_id}/.default",
                "client_id": "integration-tests",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def issue_token(self, audience: str, roles: list[str]) -> str:
        """Mint a token with an explicit audience and role set.

        Used by negative tests: a mismatched audience must yield 401 and a
        missing role must yield 403.
        """
        response = requests.post(
            f"{self.host_url}/issue-token",
            json={"audience": audience, "roles": roles},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["access_token"]


def create_oauth2_mock_container(
    network: Network,
    name: str = "oauth_mock",
    port: int = 8080,
    alias: str = "oauth-mock",
    test_id: str = "",
) -> tuple[StreamLoggingDockerContainer, OAuth2Mock]:
    """Build the image and return both the raw container and a typed wrapper."""
    image: str = build_image_once(path=str(_IMAGE_DIR), tag="oauth2-mock")

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        # The issuer must match the in-network alias so that the `iss` claim, the
        # discovery document and the JWKS URI all agree for the services.
        .with_env("ISSUER_URL", f"http://{alias}:{port}")
    )

    mock = OAuth2Mock(container=container, port=port, alias=alias)
    return container, mock
