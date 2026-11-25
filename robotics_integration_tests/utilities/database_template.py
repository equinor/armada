import fcntl
import os
import uuid
from pathlib import Path
from typing import Callable

from loguru import logger
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer


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
    failure: Path = shared_dir / f"{name}.failed"

    with open(shared_dir / f"{name}.lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            if result.exists():
                return result
            if failure.exists():
                raise RuntimeError(
                    f"{name} already failed in another worker: {failure.read_text()}"
                )

            partial: Path = shared_dir / f"{name}.partial"
            try:
                action(partial)
            except Exception as error:
                failure.write_text(repr(error))
                raise
            os.replace(partial, result)
            return result
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def dump_database(database: PostgresContainer) -> bytes:
    """Schema and data as SQL, so that the migrations history table is included."""
    exit_code, (stdout, stderr) = database.get_wrapped_container().exec_run(
        [
            "pg_dump",
            "--username",
            database.username,
            "--dbname",
            database.dbname,
            "--no-owner",
            "--no-privileges",
        ],
        demux=True,
    )
    if exit_code != 0 or not stdout:
        raise RuntimeError(
            f"pg_dump failed with exit code {exit_code}: "
            f"{(stderr or b'').decode(errors='replace')}"
        )
    return stdout


def build_database_template(
    output: Path,
    create_database: Callable[..., PostgresContainer],
    create_migrations_runner: Callable[..., DockerContainer],
    connection_string: str,
) -> None:
    """Migrate a throwaway database and write a dump of it to ``output``.

    Restoring, compiling and running the migrations takes most of a minute, nearly
    all of it build time, and gives the same result for every test. Each test's own
    database loads the dump instead.
    """
    template_id: str = f"template-{uuid.uuid4().hex[:8]}"

    with Network() as network:
        with create_database(network, test_id=template_id) as database:
            with create_migrations_runner(
                network=network,
                postgres_connection_string=connection_string,
                test_id=template_id,
            ) as migrations_runner:
                # Block until the container exits; returns {"StatusCode": int}
                result = migrations_runner.get_wrapped_container().wait()
                status = int(result.get("StatusCode", 1))
                if status != 0:
                    raise RuntimeError(f"Migrator failed with exit code {status}")

            output.write_bytes(dump_database(database))

    logger.info(f"Migrations completed successfully, template written to {output}")
