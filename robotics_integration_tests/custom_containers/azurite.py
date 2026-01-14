from typing import Dict

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class AzuriteStorageContainer:
    def __init__(
        self,
        alias: str,
        container: StreamLoggingDockerContainer,
        docker_connection_string: str,
        host_connection_string: str,
    ):
        self.alias = alias
        self.container = container
        self.docker_connection_string = docker_connection_string
        self.host_connection_string = host_connection_string


class FlotillaStorage:
    def __init__(self, azurite_containers: Dict[str, AzuriteStorageContainer]) -> None:
        self.azurite_containers: Dict[str, AzuriteStorageContainer] = azurite_containers


def create_azurite_container(
    network: Network, name: str = "azurite"
) -> StreamLoggingDockerContainer:
    # Command binds services to 0.0.0.0 so Docker can map ports
    cmd: str = (
        "azurite --blobHost 0.0.0.0 --queueHost 0.0.0.0 --tableHost 0.0.0.0 --skipApiVersionCheck"
    )

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=settings.AZURITE_IMAGE, command=cmd)
        .with_name(name)
        .with_network(network)
        .with_network_aliases(name)
        .with_exposed_ports(10000)
    )
    return container


def azurite_connection_string_for_containers(
    azurite_account: str, azurite_key: str, azurite_alias: str, port: int
) -> str:
    return (
        "DefaultEndpointsProtocol=http;"
        f"AccountName={azurite_account};"
        f"AccountKey={azurite_key};"
        f"BlobEndpoint=http://{azurite_alias}:{port}/{azurite_account};"
    )


def ensure_blob_containers(connection_string: str, *names: str) -> None:
    svc: BlobServiceClient = BlobServiceClient.from_connection_string(connection_string)
    for name in names:
        try:
            svc.create_container(name)
        except ResourceExistsError:
            pass
