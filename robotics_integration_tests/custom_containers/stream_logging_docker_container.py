from threading import Thread
from typing import Optional, Any, Self

from docker.errors import DockerException
from docker.types.daemon import CancellableStream
from loguru import logger
from requests.exceptions import RequestException
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy

_LOG_JOIN_TIMEOUT = 5


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

        self.logging_thread: Thread | None = None
        self._log_stream: CancellableStream | None = None

    def start(self) -> Self:
        super().start()
        self._log_stream = self.get_wrapped_container().logs(stream=True, follow=True)
        self.logging_thread = Thread(
            target=self._stream_logs,
            args=(self._log_stream,),
            name=f"{self._name}-logs",
            daemon=True,
        )
        self.logging_thread.start()
        return self

    def stop(self, force: bool = True, delete_volume: bool = True) -> None:
        try:
            super().stop(force=force, delete_volume=delete_volume)
        finally:
            if self.logging_thread is not None:
                # Removal normally ends the stream; drain the final startup/shutdown logs.
                self.logging_thread.join(timeout=_LOG_JOIN_TIMEOUT)
                if self.logging_thread.is_alive() and self._log_stream is not None:
                    try:
                        self._log_stream.close()
                    except (DockerException, OSError) as error:
                        logger.warning(
                            f"{self._name}: failed to close log stream: {error}"
                        )
                    finally:
                        self.logging_thread.join(timeout=_LOG_JOIN_TIMEOUT)
                if self.logging_thread.is_alive():
                    logger.warning(
                        f"{self._name}: log thread did not stop within timeout"
                    )

    def _stream_logs(self, stream: CancellableStream) -> None:
        try:
            for line in stream:
                logger.info(f"{self._name}: {line.decode(errors='replace').rstrip()}")
        except (DockerException, RequestException) as error:
            logger.exception(f"{self._name}: failed to stream container logs: {error}")
