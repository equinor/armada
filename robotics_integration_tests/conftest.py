import time
from contextlib import ExitStack
from typing import Dict

import pytest
from loguru import logger
from testcontainers.core.network import Network

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.azurite import (
    create_azurite_container,
    azurite_connection_string_for_containers,
    ensure_blob_containers,
    FlotillaStorage,
    AzuriteStorageContainer,
)
from robotics_integration_tests.custom_containers.flotilla_backend import (
    create_flotilla_backend_container,
    FlotillaBackend,
)
from robotics_integration_tests.custom_containers.isar import (
    create_isar_robot_container,
    IsarRobot,
)
from robotics_integration_tests.custom_containers.migrations_runner import (
    create_migrations_runner_container,
)
from robotics_integration_tests.custom_containers.mosquitto import (
    create_flotilla_broker_container,
    FlotillaBroker,
)
from robotics_integration_tests.custom_containers.postgres import (
    create_postgres_container,
    FlotillaDatabase,
)
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.flotilla_backend_api import (
    wait_for_backend_to_be_responsive,
    populate_database_with_minimum_models,
    wait_for_database_to_be_populated,
    wait_for_robot_to_be_populated_in_database,
    get_robot_by_name,
    get_inspection_area_id_for_installation,
    set_current_inspection_area_for_robot,
    wait_for_inspection_area_to_be_updated_on_robot,
)
from robotics_integration_tests.utilities.keyvault import Keyvault


@pytest.fixture
def keyvault():
    keyvault: Keyvault = Keyvault(
        keyvault_name=settings.KEYVAULT_NAME,
        client_secret=settings.FLOTILLA_AZURE_CLIENT_SECRET,
        client_id=settings.FLOTILLA_AZURE_CLIENT_ID,
        tenant_id=settings.AZURE_TENANT_ID,
    )

    yield keyvault


@pytest.fixture
def network():
    with Network() as network:
        yield network


@pytest.fixture
def flotilla_database(network: Network, keyvault: Keyvault):
    with create_postgres_container(network) as database:
        logger.info(
            f"Postgres URL: {database.get_connection_url()}, "
            f"Port: {database.get_exposed_port(5432)}"
        )

        connection_string: str = (
            f"Host={settings.DB_ALIAS}; Port={5432}; Username={settings.DB_USER}; Password={settings.DB_PASSWORD}; "
            f"Database={settings.DB_ALIAS}; SSL Mode=Disable;"
        )

        with create_migrations_runner_container(
            network=network,
            postgres_connection_string=connection_string,
        ) as migrations_runner:
            # Block until the container exits; returns {"StatusCode": int}
            result = migrations_runner.get_wrapped_container().wait()
            status = int(result.get("StatusCode", 1))
            if status != 0:
                raise RuntimeError(f"Migrator failed with exit code {status}")

        logger.info("Migrations completed successfully (container exited cleanly)")

        keyvault.set_secret(
            secret_name="flotilla-database-connection-string",
            secret_value=connection_string,
        )

        yield FlotillaDatabase(
            database=database,
            connection_string=connection_string,
            alias=settings.DB_ALIAS,
        )


@pytest.fixture
def flotilla_storage(network: Network, keyvault: Keyvault):
    with ExitStack() as stack:
        azurite_containers: Dict[str, AzuriteStorageContainer] = {}

        for azurite_container_alias in settings.AZURITE_ALIASES:
            container: StreamLoggingDockerContainer = stack.enter_context(
                create_azurite_container(network=network, name=azurite_container_alias)
            )

            docker_connection_string: str = azurite_connection_string_for_containers(
                settings.AZURITE_ACCOUNT,
                settings.AZURITE_KEY,
                azurite_container_alias,
                port=10000,
            )
            host_connection_string: str = azurite_connection_string_for_containers(
                settings.AZURITE_ACCOUNT,
                settings.AZURITE_KEY,
                "localhost",
                port=container.get_exposed_port(10000),
            )
            azurite_containers[azurite_container_alias] = AzuriteStorageContainer(
                alias=azurite_container_alias,
                container=container,
                docker_connection_string=docker_connection_string,
                host_connection_string=host_connection_string,
            )
            if azurite_container_alias == settings.SARA_RAW_STORAGE_CONTAINER:
                keyvault.set_secret(
                    secret_name="AZURE-STORAGE-CONNECTION-STRING-DATA",
                    secret_value=docker_connection_string,
                )
            elif azurite_container_alias == settings.SARA_ANON_STORAGE_CONTAINER:
                keyvault.set_secret(
                    secret_name="AZURE-STORAGE-CONNECTION-STRING-METADATA",
                    secret_value=docker_connection_string,
                )

            ensure_blob_containers(host_connection_string, "hua", "kaa", "nls", "test")

        yield FlotillaStorage(azurite_containers=azurite_containers)


@pytest.fixture
def flotilla_broker(network: Network):
    with create_flotilla_broker_container(
        network=network,
        image=settings.FLOTILLA_BROKER_IMAGE,
        name=settings.FLOTILLA_BROKER_NAME,
        port=settings.FLOTILLA_BROKER_PORT,
        alias=settings.FLOTILLA_BROKER_ALIAS,
    ) as broker:

        yield FlotillaBroker(
            broker=broker,
            name=settings.FLOTILLA_BROKER_NAME,
            port=settings.FLOTILLA_BROKER_PORT,
            alias=settings.FLOTILLA_BROKER_ALIAS,
        )


@pytest.fixture
def flotilla_backend(network: Network, flotilla_database: FlotillaDatabase):
    with create_flotilla_backend_container(
        network=network,
        database_connection_string=flotilla_database.connection_string,
        image=settings.FLOTILLA_BACKEND_IMAGE,
        name=settings.FLOTILLA_BACKEND_NAME,
        port=settings.FLOTILLA_BACKEND_PORT,
        alias=settings.FLOTILLA_BACKEND_ALIAS,
    ) as flotilla_backend:
        backend_url: str = f"http://localhost:{flotilla_backend.get_exposed_port(8000)}"
        wait_for_backend_to_be_responsive(backend_url=backend_url)
        populate_database_with_minimum_models(backend_url=backend_url)
        wait_for_database_to_be_populated(backend_url=backend_url)

        yield FlotillaBackend(
            flotilla_backend=flotilla_backend,
            backend_url=backend_url,
            name=settings.FLOTILLA_BACKEND_NAME,
            port=settings.FLOTILLA_BACKEND_PORT,
            alias=settings.FLOTILLA_BACKEND_ALIAS,
        )


@pytest.fixture
def armada_without_robots(
    keyvault: Keyvault,
    network: Network,
    flotilla_database: FlotillaDatabase,
    flotilla_storage: FlotillaStorage,
    flotilla_broker: FlotillaBroker,
    flotilla_backend: FlotillaBackend,
):
    armada: Armada = Armada()

    armada.keyvault = keyvault
    armada.network = network
    armada.flotilla_database = flotilla_database
    armada.flotilla_storage = flotilla_storage
    armada.flotilla_broker = flotilla_broker
    armada.flotilla_backend = flotilla_backend

    yield armada


@pytest.fixture
def armada_with_single_robot(armada_without_robots: Armada):
    armada: Armada = armada_without_robots

    with create_isar_robot_container(
        network=armada.network,
        image=settings.ISAR_ROBOT_IMAGE,
        name=settings.ISAR_ROBOT_NAME,
        port=settings.ISAR_ROBOT_PORT,
        alias=settings.ISAR_ROBOT_ALIAS,
    ) as isar_robot:

        wait_for_robot_to_be_populated_in_database(
            backend_url=armada.flotilla_backend.backend_url,
            robot_name=settings.ISAR_ROBOT_NAME,
        )

        robot: Dict = get_robot_by_name(
            backend_url=armada.flotilla_backend.backend_url,
            name=settings.ISAR_ROBOT_NAME,
        )
        installation_code_for_robot: str = robot.get("currentInstallation").get(
            "installationCode"
        )
        robot_id: str = robot.get("id")

        inspection_area_id: str = get_inspection_area_id_for_installation(
            backend_url=armada.flotilla_backend.backend_url,
            installation_code=installation_code_for_robot,
        )

        set_current_inspection_area_for_robot(
            backend_url=armada.flotilla_backend.backend_url,
            inspection_area_id=inspection_area_id,
            robot_id=robot_id,
        )
        wait_for_inspection_area_to_be_updated_on_robot(
            backend_url=armada.flotilla_backend.backend_url, robot_id=robot_id
        )

        armada.robots[settings.ISAR_ROBOT_NAME] = IsarRobot(
            container=isar_robot,
            name=settings.ISAR_ROBOT_NAME,
            robot_id=robot_id,
            port=settings.ISAR_ROBOT_PORT,
            alias=settings.ISAR_ROBOT_ALIAS,
            installation_code=installation_code_for_robot,
        )

        logger.info("Armada has been deployed")
        logger.info(
            f"Broker exposed port is {armada.flotilla_broker.broker.get_exposed_port(1883)}"
        )
        logger.info(
            f"Backend exposed port is {armada.flotilla_backend.container.get_exposed_port(8000)}"
        )
        logger.info(f"ISAR Robot exposed port is {isar_robot.get_exposed_port(3000)}")

        yield armada
