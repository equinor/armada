from threading import Event
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError
from requests.exceptions import ConnectionError
from testcontainers.core.container import DockerContainer
from testcontainers.core.exceptions import ContainerStartException

from robotics_integration_tests.custom_containers import stream_logging_docker_container
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)


@pytest.fixture
def started_container(monkeypatch):
    wrapped = MagicMock()

    def start(container):
        container._container = wrapped
        return container

    monkeypatch.setattr(DockerContainer, "start", start)
    monkeypatch.setattr(stream_logging_docker_container, "_LOG_JOIN_TIMEOUT", 0.1)
    return wrapped


def test_construction_and_stop_without_start_do_not_start_logging(docker_client):
    container = StreamLoggingDockerContainer("test")
    assert container.logging_thread is None
    with pytest.raises(ContainerStartException):
        container.get_wrapped_container()
    container.stop()
    docker_client.client.close.assert_called_once()


def test_failed_start_does_not_start_logging(monkeypatch, docker_client):
    def fail_start(container):
        raise APIError("start failed")

    monkeypatch.setattr(DockerContainer, "start", fail_start)
    container = StreamLoggingDockerContainer("test")
    with pytest.raises(APIError, match="start failed"):
        with container:
            pytest.fail("failed container must not be yielded")
    assert container.logging_thread is None
    docker_client.client.close.assert_called_once()


def test_context_streams_early_exit_logs_and_joins(started_container, monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(stream_logging_docker_container, "logger", log)
    stream = MagicMock()
    stream.__iter__.return_value = iter([b"startup failed\n", b"invalid byte: \xff\n"])
    started_container.logs.return_value = stream
    container = StreamLoggingDockerContainer("test").with_name("sara-test")

    with container as entered:
        assert entered is container
        assert container.logging_thread is not None
    assert not container.logging_thread.is_alive()
    started_container.logs.assert_called_once_with(stream=True, follow=True)
    log.info.assert_any_call("sara-test: startup failed")
    log.info.assert_any_call("sara-test: invalid byte: \ufffd")
    started_container.remove.assert_called_once_with(force=True, v=True)


@pytest.mark.parametrize("remove_fails", [False, True])
def test_stop_cancels_blocked_stream_even_if_removal_fails(
    started_container, remove_fails
):
    reading = Event()
    closed = Event()

    def lines():
        reading.set()
        assert closed.wait(timeout=5), "stop did not cancel log stream"
        yield from ()

    stream = MagicMock()
    stream.__iter__.return_value = lines()
    stream.close.side_effect = closed.set
    started_container.logs.return_value = stream
    if remove_fails:
        started_container.remove.side_effect = APIError("remove failed")

    container = StreamLoggingDockerContainer("test").start()
    try:
        assert reading.wait(timeout=5)
        if remove_fails:
            with pytest.raises(APIError, match="remove failed"):
                container.stop(force=False, delete_volume=False)
        else:
            container.stop(force=False, delete_volume=False)
        assert container.logging_thread is not None
        assert not container.logging_thread.is_alive()
        stream.close.assert_called_once()
        started_container.remove.assert_called_once_with(force=False, v=False)
    finally:
        closed.set()
        container.logging_thread.join(timeout=5)


@pytest.mark.parametrize("error", [APIError("stream failed"), ConnectionError("lost")])
def test_stream_errors_are_logged(started_container, monkeypatch, error):
    log = MagicMock()
    monkeypatch.setattr(stream_logging_docker_container, "logger", log)
    stream = MagicMock()
    stream.__iter__.side_effect = error
    started_container.logs.return_value = stream

    with StreamLoggingDockerContainer("test").with_name("sara-test") as container:
        pass
    assert container.logging_thread is not None
    assert not container.logging_thread.is_alive()
    log.exception.assert_called_once_with(
        f"sara-test: failed to stream container logs: {error}"
    )
