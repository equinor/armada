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
