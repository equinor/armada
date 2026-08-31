from typing import Dict, List

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class AzuriteStorageContainer:
    """One Azurite instance.

    Every instance serves all of the pipeline's storage account names, so that
    the account a caller addresses is independent of which instance holds the
    data. The instance is chosen by network alias; ``account`` is the one this
    instance is nominally for, and the one the convenience connection strings
    below are built with.
    """

    def __init__(
        self,
        alias: str,
        account: str,
        port: int,
        host_port: int,
        container: StreamLoggingDockerContainer,
    ):
        self.alias = alias
        self.account = account
        self.port = port
        self.host_port = host_port
        self.container = container

    def connection_string_for(self, account: str, from_host: bool = False) -> str:
        """Connection string addressing a specific account on this instance."""
        if from_host:
            return azurite_connection_string_for_containers(
                account, settings.AZURITE_KEY, "localhost", self.host_port
            )
        return azurite_connection_string_for_containers(
            account, settings.AZURITE_KEY, self.alias, self.port
        )

    @property
    def docker_connection_string(self) -> str:
        return self.connection_string_for(self.account)

    @property
    def host_connection_string(self) -> str:
        return self.connection_string_for(self.account, from_host=True)


class ArmadaStorage:
    def __init__(self, azurite_containers: Dict[str, AzuriteStorageContainer]) -> None:
        self.azurite_containers: Dict[str, AzuriteStorageContainer] = azurite_containers

    def connection_strings_by_account(self) -> Dict[str, str]:
        """In-network connection string per storage account name.

        SARA and the Argo stub both address storage by account name rather than
        by container alias, so this is the shape both of them need. It is what
        routes each stage of the pipeline to its own Azurite instance.
        """
        return {
            storage.account: storage.docker_connection_string
            for storage in self.azurite_containers.values()
        }


def create_azurite_container(
    network: Network, accounts: List[str], name: str = "azurite", test_id: str = ""
) -> StreamLoggingDockerContainer:
    # Command binds services to 0.0.0.0 so Docker can map ports
    cmd: str = (
        "azurite --blobHost 0.0.0.0 --queueHost 0.0.0.0 --tableHost 0.0.0.0 --skipApiVersionCheck"
    )

    account_spec = ";".join(f"{account}:{settings.AZURITE_KEY}" for account in accounts)

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=settings.AZURITE_IMAGE, command=cmd)
        .with_name(f"{name}-{test_id}")
        .with_network(network)
        .with_network_aliases(name)
        .with_exposed_ports(10000)
        .with_env("AZURITE_ACCOUNTS", account_spec)
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
