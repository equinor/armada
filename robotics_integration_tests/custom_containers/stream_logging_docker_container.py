import time
from threading import Thread
from typing import Optional, Any

from loguru import logger
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy


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

        self.logging_thread: Thread = Thread(target=self._stream_logs)
        self.logging_thread.start()

    def _stream_logs(self) -> None:
        while not self.get_wrapped_container():
            time.sleep(0.1)
        for line in self.get_wrapped_container().logs(stream=True, follow=True):
            logger.info(f"{self._name}: {line.decode().rstrip()}")
