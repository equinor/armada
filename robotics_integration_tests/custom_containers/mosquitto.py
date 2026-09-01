from docker.models.networks import Network
from testcontainers.core.container import DockerContainer

from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.mqtt_credentials import MqttCredentials


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
    mqtt_credentials: MqttCredentials,
    image: str = "ghcr.io/equinor/flotilla-broker:latest",
    name: str = "flotilla_broker",
    port: int = 1883,
    alias: str = "broker",
    test_id: str = "",
) -> DockerContainer:
    container: DockerContainer = (
        DockerContainer(image=image)
        .with_kwargs(platform="linux/amd64")
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network=network)
        .with_network_aliases(alias)
        # Generated per test run; the certificate is issued for `alias`.
        .with_env("MQTT_PASSWORDS", mqtt_credentials.broker_password_list)
        .with_env("TLS_SERVER_KEY", mqtt_credentials.server_key)
        .with_env("TLS_SERVER_CERT", mqtt_credentials.server_certificate)
        .with_env("TLS_CA_CERT", mqtt_credentials.ca_certificate)
    )

    return container
