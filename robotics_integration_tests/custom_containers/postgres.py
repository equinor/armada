from docker.models.networks import Network
from testcontainers.postgres import PostgresContainer

from robotics_integration_tests.settings.settings import settings


class FlotillaDatabase:
    def __init__(
        self, database: PostgresContainer, connection_string: str, alias: str
    ) -> None:
        self.database: PostgresContainer = database
        self.connection_string: str = connection_string
        self.alias: str = alias


def create_postgres_container(network: Network) -> PostgresContainer:
    container: PostgresContainer = (
        PostgresContainer(
            image=settings.POSTGRESQL_IMAGE,
            username=settings.DB_USER,
            password=settings.DB_PASSWORD,
            dbname=settings.DB_ALIAS,
        )
        .with_name(settings.DB_ALIAS)
        .with_exposed_ports(5432)
        .with_network(network)
        .with_network_aliases(settings.DB_ALIAS)
    )

    return container


class SaraDatabase:
    def __init__(
        self, database: PostgresContainer, connection_string: str, alias: str
    ) -> None:
        self.database: PostgresContainer = database
        self.connection_string: str = connection_string
        self.alias: str = alias


def create_sara_postgres_container(network: Network) -> PostgresContainer:
    container: PostgresContainer = (
        PostgresContainer(
            image=settings.POSTGRESQL_IMAGE,
            username=settings.SARA_DB_USER,
            password=settings.SARA_DB_PASSWORD,
            dbname=settings.SARA_DB_ALIAS,
        )
        .with_name(settings.SARA_DB_ALIAS)
        .with_exposed_ports(5432)
        .with_network(network)
        .with_network_aliases(settings.SARA_DB_ALIAS)
    )

    return container
