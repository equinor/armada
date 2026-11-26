import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer


@dataclass(frozen=True)
class DatabaseTemplateSpec:
    """What is needed to build the database template of one service."""

    file_name: str
    create_database: Callable[..., PostgresContainer]
    create_migrations_runner: Callable[..., DockerContainer]
    connection_string: str


def build_database_template(output: Path, spec: DatabaseTemplateSpec) -> None:
    """Migrate a throwaway database and write a dump of it to ``output``.

    Restoring, compiling and running the migrations takes most of a minute, nearly
    all of it build time, and gives the same result for every test. Each test's own
    database loads the dump instead.
    """
    template_id: str = f"template-{uuid.uuid4().hex[:8]}"

    with (
        Network() as network,
        spec.create_database(network, test_id=template_id) as database,
    ):
        _run_migrations(network, spec, template_id)
        output.write_bytes(dump_database(database))

    logger.info(f"Migrations completed successfully, template written to {output}")


def _run_migrations(
    network: Network, spec: DatabaseTemplateSpec, template_id: str
) -> None:
    with spec.create_migrations_runner(
        network=network,
        postgres_connection_string=spec.connection_string,
        test_id=template_id,
    ) as migrations_runner:
        # Block until the container exits; returns {"StatusCode": int}
        result = migrations_runner.get_wrapped_container().wait()

    status = int(result.get("StatusCode", 1))
    if status != 0:
        raise RuntimeError(f"Migrator failed with exit code {status}")


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
