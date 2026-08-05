import time
from pathlib import Path

import requests
from docker.models.networks import Network
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings

_REALM_DIR = Path(__file__).resolve().parent.parent / "custom_realms"

REALM = "robotics"

# Confidential clients declared in custom_realms/robotics-realm.json. The secrets
# are not secret: the realm is a fixture, reachable only from the test network and
# a developer's machine.
#
# These are constants rather than settings on purpose. Making the first one a
# setting named INTEGRATION_TESTS_CLIENT_SECRET would let the stale Entra value of
# that name -- still present in many developers' .env files, in this repository's
# workflow and in every consuming repository's secrets -- silently override it,
# and the only symptom would be an unexplained 401.
INTEGRATION_TESTS_CLIENT = "integration-tests"
INTEGRATION_TESTS_SECRET = "integration-tests-secret"

# Holds Role.User.HUA and nothing else: a recognised principal that still lacks
# Flotilla admin rights and ISAR's Mission.Control.
LIMITED_ROLE_CLIENT = "integration-tests-limited-role"
LIMITED_ROLE_SECRET = "integration-tests-limited-role-secret"

# Holds no roles at all. Kept distinct from the client above because Flotilla
# answers 403 for an insufficient role but 401 for a token with no roles.
NO_ROLE_CLIENT = "integration-tests-no-role"
NO_ROLE_SECRET = "integration-tests-no-role-secret"


class Keycloak:
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
        return f"http://{self.alias}:{self.port}/realms/{REALM}"

    @property
    def internal_openid_config_url(self) -> str:
        """Discovery document URL to hand to the services."""
        return f"{self.internal_url}/.well-known/openid-configuration"

    @property
    def host_url(self) -> str:
        """Realm URL reachable from the test host."""
        port = self.container.get_exposed_port(self.port)
        return f"http://localhost:{port}/realms/{REALM}"

    @property
    def token_url(self) -> str:
        return f"{self.host_url}/protocol/openid-connect/token"

    def wait_until_ready(self, timeout: int = 180) -> None:
        """Block until the realm can actually mint a token.

        Polling the discovery document is not enough. It starts answering while
        the realm's clients are still being imported, and a token requested in
        that window comes back 401 -- which then surfaces much later as an
        unexplained authentication failure in a test. Minting a real token is the
        only check that proves the clients, scopes and service accounts are all
        in place.
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
        """Mint a token through the client credentials flow.

        ``scope`` names a client scope in the realm -- ``isar-api``, ``sara-api``,
        ``flotilla-api`` or ``pointilla-api`` -- each of which carries a single
        audience mapper. Request exactly one: with two, Keycloak emits ``aud`` as
        an array, which ISAR's token model rejects.
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

    def get_token_without_roles(self, scope: str) -> str:
        """Mint a token with a correct audience but no roles.

        Keycloak has no equivalent of an ad-hoc "issue me a token with these
        claims" endpoint, so a role set is chosen by picking the service account
        that holds it. This one holds none.
        """
        return self.get_token(
            scope=scope,
            client_id=NO_ROLE_CLIENT,
            client_secret=NO_ROLE_SECRET,
        )


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
        # Admin console credentials. The console is not used by the tests; Keycloak
        # requires a bootstrap admin to start.
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin")
        # Tokens are minted from the host but validated inside the network, so the
        # issuer must be the in-network name in both cases.
        .with_env("KC_HOSTNAME", f"http://{alias}:{port}")
        .with_env("KC_HOSTNAME_BACKCHANNEL_DYNAMIC", "false")
        .with_volume_mapping(str(_REALM_DIR), "/opt/keycloak/data/import", mode="ro")
    )

    keycloak = Keycloak(container=container, port=port, alias=alias)
    return container, keycloak
