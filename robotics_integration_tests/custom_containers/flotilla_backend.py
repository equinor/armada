from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class FlotillaBackend:
    def __init__(
        self,
        flotilla_backend: StreamLoggingDockerContainer,
        backend_url: str,
        name: str,
        port: int,
        alias: str,
    ) -> None:
        self.container: StreamLoggingDockerContainer = flotilla_backend
        self.backend_url: str = backend_url
        self.name: str = name
        self.port: int = port
        self.alias: str = alias


def create_flotilla_backend_container(
    network: Network,
    database_connection_string: str,
    teams_notification_webhook_url: str,
    image: str = "ghcr.io/equinor/flotilla-backend:latest",
    name: str = "flotilla_backend",
    port: int = 8000,
    alias: str = "flotilla_backend",
    test_id: str = "",
) -> StreamLoggingDockerContainer:
    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_kwargs(platform="linux/amd64")
        .with_env("Mqtt__Host", settings.FLOTILLA_BROKER_ALIAS)
        .with_env("Mqtt__Port", settings.FLOTILLA_BROKER_PORT)
        .with_env("Mqtt__Password", settings.FLOTILLA_MQTT_PASSWORD)
        # Selects appsettings.IntegrationTest.json, which sets
        # Authentication:Provider to Oidc, points token validation at the Keycloak
        # realm, and turns off Key Vault and Redis.
        .with_env("ASPNETCORE_ENVIRONMENT", settings.ASPNETCORE_ENVIRONMENT)
        .with_env("Database__PostgreSqlConnectionString", database_connection_string)
        .with_env("TeamsNotification__WebhookUrl", teams_notification_webhook_url)
    )
    return container
