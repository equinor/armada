import json
from pathlib import Path
from typing import Any, Dict, List

import requests
from docker.models.networks import Network

from robotics_integration_tests.custom_containers.image_builder import build_image_once
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)

_IMAGE_DIR = Path(__file__).resolve().parent.parent / "custom_images" / "argo_stub"

# Every workflow type SARA can trigger. The stub serves one path per type purely
# so the recorded TriggerUrl is legible in a failure; it dispatches on the
# workflowType in the payload, as the real Argo event sources do.
WORKFLOW_TYPES: tuple[str, ...] = (
    "anonymizer",
    "rain-drop",
    "fencilla",
    "cloe",
    "thermal-reading",
    "copy-raw-to-visualized",
)


class ArgoStub:
    """Wraps the fake Argo container and exposes helpers to configure it and to
    inspect what SARA asked it to do."""

    def __init__(
        self,
        container: StreamLoggingDockerContainer,
        port: int,
        alias: str,
    ) -> None:
        self.container = container
        self.port = port
        self.alias = alias

    def internal_trigger_url(self, workflow_type: str) -> str:
        """Trigger URL as SARA reaches it, on the shared Docker network."""
        return f"http://{self.alias}:{self.port}/trigger/{workflow_type}"

    @property
    def host_url(self) -> str:
        return f"http://localhost:{self.container.get_exposed_port(self.port)}"

    def set_behaviour(self, behaviour: Dict[str, Dict[str, Any]]) -> None:
        """Configure per-workflow-type responses.

        Recognised keys per workflow type: ``result`` (merged into the default
        result document), ``raw_result`` (a literal string, for malformed
        results), ``exit_status`` (``Succeeded`` | ``Failed``),
        ``trigger_status`` (HTTP status returned to SARA on trigger),
        ``error_message``, ``delay_seconds`` and ``write_output_blob``.
        """
        response = requests.post(f"{self.host_url}/behaviour", json=behaviour, timeout=10)
        response.raise_for_status()

    def get_triggers(self) -> List[dict]:
        """Trigger payloads SARA has sent, in arrival order."""
        response = requests.get(f"{self.host_url}/triggers", timeout=10)
        response.raise_for_status()
        return response.json()

    def get_triggered_workflow_types(self) -> List[str]:
        return [trigger.get("workflowType", "") for trigger in self.get_triggers()]

    def get_callbacks(self) -> List[dict]:
        """Callbacks the stub has made back into SARA, in arrival order."""
        response = requests.get(f"{self.host_url}/callbacks", timeout=10)
        response.raise_for_status()
        return response.json()

    def wait_until_ready(self, timeout: int = 60) -> None:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if requests.get(f"{self.host_url}/health", timeout=5).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError(f"Argo stub was not responsive within {timeout}s")


def create_argo_stub_container(
    network: Network,
    sara_internal_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    token_scope: str,
    blob_connection_strings_by_account: Dict[str, str],
    name: str = "argo_stub",
    port: int = 8080,
    alias: str = "argo_stub",
    test_id: str = "",
) -> tuple[StreamLoggingDockerContainer, ArgoStub]:
    """Build the image and return both the raw container and a typed wrapper."""
    image: str = build_image_once(path=str(_IMAGE_DIR), tag="argo-stub")

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_env("SARA_BASE_URL", sara_internal_url)
        .with_env("TOKEN_URL", token_url)
        .with_env("CLIENT_ID", client_id)
        .with_env("CLIENT_SECRET", client_secret)
        .with_env("TOKEN_SCOPE", token_scope)
        .with_env("BLOB_CONNECTION_STRINGS", json.dumps(blob_connection_strings_by_account))
    )

    return container, ArgoStub(container=container, port=port, alias=alias)
