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
    image: str = "ghcr.io/equinor/flotilla-backend:latest",
    name: str = "flotilla_backend",
    port: int = 8000,
    alias: str = "flotilla_backend",
) -> StreamLoggingDockerContainer:
    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(name)
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_env("Mqtt__Host", settings.FLOTILLA_BROKER_ALIAS)
        .with_env("Mqtt__Port", settings.FLOTILLA_BROKER_PORT)
        .with_env("Mqtt__Password", settings.FLOTILLA_MQTT_PASSWORD)
        .with_env("ASPNETCORE_ENVIRONMENT", settings.ASPNETCORE_ENVIRONMENT)
        .with_env("AZURE_CLIENT_SECRET", settings.FLOTILLA_AZURE_CLIENT_SECRET)
        .with_env("AZURE_CLIENT_ID", settings.FLOTILLA_AZURE_CLIENT_ID)
        .with_env("AZURE_TENANT_ID", settings.AZURE_TENANT_ID)
        .with_env("KeyVault__VaultUri", settings.KEYVAULT_URI)
        .with_env("Database__PostgreSqlConnectionString", database_connection_string)
        .with_env("AzureAd__ClientSecret", settings.FLOTILLA_AZURE_CLIENT_SECRET)
    )

    return container
