import fcntl
import os
from pathlib import Path
from typing import Callable


def run_once_per_session(
    shared_dir: Path, name: str, action: Callable[[Path], None]
) -> Path:
    """Run ``action`` once per pytest run, however many xdist workers ask for it.

    ``action`` is given a path to write its result to, and that result is what every
    caller gets back. ``shared_dir`` must be the same directory for all workers.

    A failure is recorded and re-raised to the other workers instead of being
    retried, so a broken migration fails the run once rather than once per worker.
    """
    result: Path = shared_dir / name
    partial: Path = shared_dir / f"{name}.partial"
    failure: Path = shared_dir / f"{name}.failed"

    # The lock is held until the file is closed, so the other workers wait here
    # while the first one runs the action.
    with open(shared_dir / f"{name}.lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)

        if result.exists():
            return result
        if failure.exists():
            raise RuntimeError(
                f"{name} already failed in another worker: {failure.read_text()}"
            )

        try:
            action(partial)
        except Exception as error:
            failure.write_text(repr(error))
            raise

        # Renamed only when complete, so a result that exists is never half written.
        os.replace(partial, result)
        return result
