from docker.models.networks import Network

from robotics_integration_tests.custom_containers.keycloak import Keycloak
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class Sara:
    def __init__(
        self,
        sara: StreamLoggingDockerContainer,
        backend_url: str,
        name: str,
        port: int,
        alias: str,
    ) -> None:
        self.container: StreamLoggingDockerContainer = sara
        self.backend_url: str = backend_url
        self.name: str = name
        self.port: int = port
        self.alias: str = alias


def create_sara_container(
    network: Network,
    keycloak: Keycloak,
    database_connection_string: str,
    raw_storage_connection_string: str,
    image: str = "ghcr.io/equinor/sara:latest",
    name: str = "sara",
    port: int = 8100,
    alias: str = "sara",
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
        .with_env("Mqtt__Password", settings.SARA_MQTT_PASSWORD)
        .with_env("Mqtt__Username", "sara")
        .with_env("ASPNETCORE_ENVIRONMENT", settings.ASPNETCORE_ENVIRONMENT)
        .with_env("Authentication__Provider", "Oidc")
        .with_env("AzureAd__Authority", keycloak.internal_url)
        .with_env("AzureAd__ClientId", settings.SARA_AUDIENCE)
        .with_env("KeyVault__UseKeyVault", "false")
        .with_env("Database__postgresConnectionString", database_connection_string)
        .with_env("Storage__RawStorageAccount", settings.AZURITE_ACCOUNT)
        .with_env(
            f"BlobStorage__{settings.AZURITE_ACCOUNT}__ConnectionString",
            raw_storage_connection_string,
        )
    )

    return container
