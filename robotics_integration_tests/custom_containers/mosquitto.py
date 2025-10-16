from docker.models.networks import Network
from testcontainers.core.container import DockerContainer

from robotics_integration_tests.settings.settings import settings


class FlotillaBroker:
    def __init__(
        self, broker: DockerContainer, name: str, port: int, alias: str
    ) -> None:
        self.broker = broker
        self.name = name
        self.port = port
        self.alias = alias


def create_flotilla_broker_container(
    network: Network,
    image: str = "ghcr.io/equinor/flotilla-broker:latest",
    name: str = "flotilla_broker",
    port: int = 1883,
    alias: str = "broker",  # Must be named "broker" due to the certificate expecting this name
) -> DockerContainer:
    container: DockerContainer = (
        DockerContainer(image=image)
        .with_name(name)
        .with_exposed_ports(port)
        .with_network(network=network)
        .with_network_aliases(alias)
        .with_env("TLS_SERVER_KEY", settings.FLOTILLA_BROKER_SERVER_KEY)
    )

    return container
