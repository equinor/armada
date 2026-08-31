import time
from pathlib import Path

import requests
from docker.models.networks import Network
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings

_REALM_DIR = Path(__file__).resolve().parent.parent / "custom_realms"

REALM = settings.KEYCLOAK_REALM

# Clients declared in custom_realms/robotics-realm.json; the secrets are fixture
# values. Constants rather than settings -- see the note in settings.py.
INTEGRATION_TESTS_CLIENT = "integration-tests"
INTEGRATION_TESTS_SECRET = "integration-tests-secret"

# Holds Role.User.HUA only: recognised, but without Flotilla admin rights or
# ISAR's Mission.Control.
LIMITED_ROLE_CLIENT = "integration-tests-limited-role"
LIMITED_ROLE_SECRET = "integration-tests-limited-role-secret"


class Keycloak:
    """Local OpenID Connect issuer replacing Azure Entra ID for the test run."""

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
        return f"http://{self.alias}:{self.port}/realms/{REALM}"

    @property
    def internal_openid_config_url(self) -> str:
        return f"{self.internal_url}/.well-known/openid-configuration"

    @property
    def internal_token_url(self) -> str:
        """Token endpoint as reached from another container on the network."""
        return f"{self.internal_url}/protocol/openid-connect/token"

    @property
    def host_url(self) -> str:
        port = self.container.get_exposed_port(self.port)
        return f"http://localhost:{port}/realms/{REALM}"

    @property
    def token_url(self) -> str:
        return f"{self.host_url}/protocol/openid-connect/token"

    def wait_until_ready(self, timeout: int = 180) -> None:
        """Block until the realm can mint a token.

        The discovery document answers while the clients are still importing, and a
        token requested in that window comes back 401.
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = requests.get(
                    f"{self.host_url}/.well-known/openid-configuration", timeout=5
                )
                if response.ok:
                    self.get_token(scope=f"{settings.ISAR_SCOPE}")
                    return
            except requests.RequestException as error:  # pragma: no cover - timing
                last_error = error
            time.sleep(0.5)
        raise TimeoutError(
            f"keycloak did not become ready within {timeout}s: {last_error}"
        )

    def get_token(
        self,
        scope: str,
        client_id: str = INTEGRATION_TESTS_CLIENT,
        client_secret: str = INTEGRATION_TESTS_SECRET,
    ) -> str:
        """Mint a token. Request exactly one scope: two audience mappers make
        Keycloak emit ``aud`` as an array, which ISAR rejects.
        """
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "scope": scope,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["access_token"]



def create_keycloak_container(
    network: Network,
    name: str = "keycloak",
    port: int = 8080,
    alias: str = "keycloak",
    test_id: str = "",
) -> tuple[StreamLoggingDockerContainer, Keycloak]:
    """Start Keycloak with the robotics realm imported."""
    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=settings.KEYCLOAK_IMAGE)
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_command("start-dev --import-realm")
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin")
        # Tokens are minted from the host but validated in-network, so the issuer
        # must be the in-network name in both cases.
        .with_env("KC_HOSTNAME", f"http://{alias}:{port}")
        .with_env("KC_HOSTNAME_BACKCHANNEL_DYNAMIC", "false")
        .with_volume_mapping(str(_REALM_DIR), "/opt/keycloak/data/import", mode="ro")
    )

    keycloak = Keycloak(container=container, port=port, alias=alias)
    return container, keycloak
