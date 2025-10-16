from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class IsarRobot:
    def __init__(
        self,
        container: StreamLoggingDockerContainer,
        name: str,
        robot_id: str,
        port: int,
        alias: str,
        installation_code: str,
    ) -> None:
        self.container: StreamLoggingDockerContainer = container
        self.name: str = name
        self.robot_id: str = robot_id
        self.port: int = port
        self.alias: str = alias
        self.installation_code: str = installation_code


def create_isar_robot_container(
    network: Network,
    image: str = "ghcr.io/equinor/isar-robot:latest",
    name: str = "isar_robot",
    port: int = 3000,
    alias: str = "isar_robot",
) -> StreamLoggingDockerContainer:

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(name)
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_env("ISAR_MQTT_ENABLED", "true")
        .with_env("ISAR_MQTT_HOST", settings.FLOTILLA_BROKER_ALIAS)
        .with_env("ISAR_MQTT_PASSWORD", settings.ISAR_MQTT_PASSWORD)
        .with_env("AZURE_CLIENT_SECRET", settings.ISAR_AZURE_CLIENT_SECRET)
        .with_env("ISAR_AZURE_CLIENT_ID", settings.ISAR_AZURE_CLIENT_ID)
        .with_env("ISAR_AZURE_TENANT_ID", settings.ISAR_AZURE_TENANT_ID)
        .with_env("ISAR_STORAGE_BLOB_ENABLED", "true")
        .with_env("ISAR_BLOB_STORAGE_ACCOUNT_NAME", settings.AZURITE_ACCOUNT)
        .with_env("ISAR_BLOB_CONTAINER", "hua")
        .with_env("ISAR_PLANT_CODE", "Huldra")
        .with_env("ISAR_PLANT_SHORT_NAME", "HUA")
        .with_env("ISAR_KEYVAULT_NAME", "FlotillaTestsKv")
        .with_env("ISAR_API_HOST_VIEWED_EXTERNALLY", "isar_robot")
    )
    return container
