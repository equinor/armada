from pathlib import Path
from typing import List

import requests
from docker.models.networks import Network
from loguru import logger
from testcontainers.core.image import DockerImage

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)

_IMAGE_DIR = Path(__file__).resolve().parent.parent / "custom_images" / "teams_webhook_receiver"


class TeamsWebhookReceiver:
    """Wraps the lightweight webhook receiver container and exposes helpers
    to retrieve captured notifications."""

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
        """URL reachable from other containers on the same Docker network."""
        return f"http://{self.alias}:{self.port}/webhook"

    @property
    def host_url(self) -> str:
        """URL reachable from the test host."""
        exposed = self.container.get_exposed_port(self.port)
        return f"http://localhost:{exposed}"

    def get_notifications(self) -> List[dict]:
        """Return all adaptive-card payloads received so far."""
        resp = requests.get(f"{self.host_url}/notifications", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_notification_messages(self) -> List[str]:
        """Extract message texts from all received adaptive card payloads.

        The message is at ``attachments[0].content.body[2].text`` in each
        notification.
        """
        messages: List[str] = []
        for notification in self.get_notifications():
            try:
                text = notification["attachments"][0]["content"]["body"][2]["text"]
                messages.append(text)
            except (KeyError, IndexError, TypeError):
                logger.warning(
                    f"Could not extract message from notification: {notification}"
                )
        return messages


def create_teams_webhook_receiver_container(
    network: Network,
    name: str = "teams_webhook_receiver",
    port: int = 8080,
    alias: str = "teams_webhook_receiver",
    test_id: str = "",
) -> tuple[StreamLoggingDockerContainer, TeamsWebhookReceiver]:
    """Build the image and return both the raw container and a typed wrapper."""
    image: DockerImage = DockerImage(
        path=str(_IMAGE_DIR),
        tag="teams-webhook-receiver",
    ).build()

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=str(image))
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
    )

    receiver = TeamsWebhookReceiver(container=container, port=port, alias=alias)
    return container, receiver
