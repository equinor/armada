from docker.models.networks import Network

from robotics_integration_tests.custom_containers.keycloak import Keycloak
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
    keycloak: Keycloak,
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
        .with_env("ASPNETCORE_ENVIRONMENT", settings.ASPNETCORE_ENVIRONMENT)
        .with_env("Authentication__Provider", "Oidc")
        .with_env("AzureAd__Authority", keycloak.internal_url)
        .with_env("AzureAd__ClientId", settings.FLOTILLA_AUDIENCE)
        .with_env("AzureAd__ClientSecret", settings.FLOTILLA_CLIENT_SECRET)
        # One scope per downstream API: two audience mappers make Keycloak emit
        # `aud` as an array, which ISAR rejects.
        .with_env("Isar__Scopes__0", settings.ISAR_SCOPE)
        .with_env("SARA__BaseUrl", f"http://{settings.SARA_ALIAS}:{settings.SARA_PORT}/")
        .with_env("SARA__Scopes__0", settings.SARA_SCOPE)
        # Both are on in flotilla's base appsettings.json.
        .with_env("KeyVault__UseKeyVault", "false")
        .with_env("Redis__UseRedis", "false")
        .with_env("Database__PostgreSqlConnectionString", database_connection_string)
        .with_env("TeamsNotification__WebhookUrl", teams_notification_webhook_url)
        .with_env("TeamsNotification__Destinations__SystemAlerts__WebhookUrl", teams_notification_webhook_url)
        .with_env("TeamsNotification__Destinations__Feedback__WebhookUrl", teams_notification_webhook_url)
    )

    return container
