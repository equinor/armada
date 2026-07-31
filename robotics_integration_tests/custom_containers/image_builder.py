import fcntl
import tempfile
from pathlib import Path

from loguru import logger
from testcontainers.core.image import DockerImage


def build_image_once(path: str, tag: str) -> str:
    """Build a local image, serialising concurrent builds of the same tag.

    Several fixtures build their image from a local Dockerfile, and each of them
    does so per test. Under ``pytest -n auto`` that means a dozen worker
    *processes* can invoke ``docker build`` for the same tag at the same moment.
    Docker does not serialise that, and the losers fail with:

        BuildError: creating image <tag> failed because it already exists, but
        accessing it also failed: No such image: <tag>

    The race is normally hidden because every worker after the first gets a full
    layer-cache hit and finishes before anyone else starts. It surfaces as soon as
    the build context changes -- exactly when someone edits one of these images --
    which makes it a confusing failure to meet.

    Session-scoped fixtures do not help here: with xdist each worker is its own
    process and runs its own session. A file lock is what actually serialises
    across processes. Once the first worker has built, the rest hit the cache and
    return almost immediately.

    Returns
    -------
    str
        The image reference to run.
    """
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
