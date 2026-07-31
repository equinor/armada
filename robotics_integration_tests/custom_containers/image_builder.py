import fcntl
import tempfile
from pathlib import Path

from loguru import logger
from testcontainers.core.image import DockerImage


def build_image_once(path: str, tag: str) -> str:
    lock_path: Path = (
        Path(tempfile.gettempdir()) / f"armada-build-{tag.replace('/', '_')}.lock"
    )

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            logger.debug(f"Building image {tag} from {path}")
            return str(DockerImage(path=path, tag=tag).build())
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
