from pathlib import Path

from docker.models.networks import Network
from testcontainers.postgres import PostgresContainer

from robotics_integration_tests.settings.settings import settings

# The postgres image runs every script in this directory when it initialises an
# empty data directory, before it accepts connections over the network.
_INIT_SQL_MOUNT = "/docker-entrypoint-initdb.d/001_schema.sql"


def _with_init_sql(
    container: PostgresContainer, init_sql_path: Path | None
) -> PostgresContainer:
    if init_sql_path is None:
        return container
    return container.with_volume_mapping(str(init_sql_path), _INIT_SQL_MOUNT, "ro")


class FlotillaDatabase:
    def __init__(
        self, database: PostgresContainer, connection_string: str, alias: str
    ) -> None:
        self.database: PostgresContainer = database
        self.connection_string: str = connection_string
        self.alias: str = alias


def create_postgres_container(
    network: Network,
    name: str = "flotilla_postgres",
    test_id: str = "",
    init_sql_path: Path | None = None,
) -> PostgresContainer:
    container: PostgresContainer = (
        PostgresContainer(
            image=settings.POSTGRESQL_IMAGE,
            username=settings.DB_USER,
            password=settings.DB_PASSWORD,
            dbname=settings.DB_ALIAS,
        )
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(5432)
        .with_network(network)
        .with_network_aliases(settings.DB_ALIAS)
    )

    return _with_init_sql(container, init_sql_path)


class SaraDatabase:
    def __init__(
        self, database: PostgresContainer, connection_string: str, alias: str
    ) -> None:
        self.database: PostgresContainer = database
        self.connection_string: str = connection_string
        self.alias: str = alias


def create_sara_postgres_container(
    network: Network,
    name: str = "sara_postgres",
    test_id: str = "",
    init_sql_path: Path | None = None,
) -> PostgresContainer:
    container: PostgresContainer = (
        PostgresContainer(
            image=settings.POSTGRESQL_IMAGE,
            username=settings.SARA_DB_USER,
            password=settings.SARA_DB_PASSWORD,
            dbname=settings.SARA_DB_ALIAS,
        )
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(5432)
        .with_network(network)
        .with_network_aliases(settings.SARA_DB_ALIAS)
    )

    return _with_init_sql(container, init_sql_path)
