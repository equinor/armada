from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="session", autouse=True)
def pull_latest_images():
    """Unit tests do not need the parent conftest's image pulls."""


@pytest.fixture(autouse=True)
def docker_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "testcontainers.core.container.DockerClient", lambda **kwargs: client
    )
    return client
