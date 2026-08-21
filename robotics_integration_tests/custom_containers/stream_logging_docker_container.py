from threading import Event, Thread
from typing import Optional, Any, Self

from loguru import logger
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy

# How long to wait for the log streaming thread to notice the container is gone.
LOGGING_THREAD_JOIN_TIMEOUT_SECONDS: float = 5.0


class StreamLoggingDockerContainer(DockerContainer):
    def __init__(
        self,
        image: str = "",
        docker_client_kw: Optional[dict[str, Any]] = None,
        _wait_strategy: Optional[WaitStrategy] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            image=image,
            docker_client_kw=docker_client_kw,
            _wait_strategy=_wait_strategy,
            **kwargs,
        )

        self.logging_thread: Optional[Thread] = None
        self._stop_logging: Event = Event()

    def start(self) -> Self:
        # The thread must only be started once the container exists, since
        # get_wrapped_container() raises ContainerStartException until then.
        super().start()

        self._stop_logging.clear()
        self.logging_thread = Thread(target=self._stream_logs, daemon=True)
        self.logging_thread.start()

        return self

    def stop(self, force: bool = True, delete_volume: bool = True) -> None:
        self._stop_logging.set()

        # Removing the container terminates the blocking log stream.
        super().stop(force=force, delete_volume=delete_volume)

        if self.logging_thread is not None:
            self.logging_thread.join(timeout=LOGGING_THREAD_JOIN_TIMEOUT_SECONDS)
            self.logging_thread = None

    def _stream_logs(self) -> None:
        try:
            for line in self.get_wrapped_container().logs(stream=True, follow=True):
                if self._stop_logging.is_set():
                    return
                logger.info(f"{self._name}: {line.decode().rstrip()}")
        except Exception as exception:
            # The stream is expected to fail once the container is removed
            # during teardown. Anything else is not worth failing a test over.
            if not self._stop_logging.is_set():
                logger.debug(f"{self._name}: log streaming stopped: {exception}")
