import os
import subprocess
import time
import uuid
from contextlib import ExitStack
from datetime import datetime
from typing import Dict

# Disable the testcontainers Reaper (Ryuk) before any testcontainers import.
# Ryuk is started lazily on the first container.start() call and queries its
# own port mapping with no retry, which races and fails sporadically when
# multiple pytest-xdist workers start containers in parallel. The suite
# already cleans up containers via `with` blocks on every fixture, so the
# Reaper's defense-in-depth value is minimal here.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import pytest
from loguru import logger
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from robotics_integration_tests.armada import Armada
from robotics_integration_tests.custom_containers.azurite import (
    create_azurite_container,
    azurite_connection_string_for_containers,
    ensure_blob_containers,
    ArmadaStorage,
    AzuriteStorageContainer,
)
from robotics_integration_tests.custom_containers.flotilla_backend import (
    create_flotilla_backend_container,
    FlotillaBackend,
)
from robotics_integration_tests.custom_containers.isar import (
    create_isar_robot_container,
    IsarRobot,
    RobotScenario,
)
from robotics_integration_tests.custom_containers.migrations_runner import (
    create_migrations_runner_container,
    create_sara_migrations_runner_container,
)
from robotics_integration_tests.custom_containers.mosquitto import (
    create_flotilla_broker_container,
    FlotillaBroker,
)
from robotics_integration_tests.custom_containers.keycloak import (
    Keycloak,
    create_keycloak_container,
)
from robotics_integration_tests.custom_containers.postgres import (
    SaraDatabase,
    create_postgres_container,
    FlotillaDatabase,
    create_sara_postgres_container,
)
from robotics_integration_tests.custom_containers.sara import (
    Sara,
    create_sara_container,
)
from robotics_integration_tests.custom_containers.teams_webhook_receiver import (
    TeamsWebhookReceiver,
    create_teams_webhook_receiver_container,
)
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication import (
    configure_issuer,
    reset_issuer,
)
from robotics_integration_tests.utilities.authentication_assertions import (
    assert_authentication_is_enforced,
    isar_url,
)
from robotics_integration_tests.utilities.flotilla_backend_api import (
    setup_robot_in_flotilla,
    wait_for_backend_to_be_responsive,
    populate_database_with_minimum_models,
    wait_for_database_to_be_populated,
)
from robotics_integration_tests.utilities.sara_backend_api import (
    wait_for_sara_to_be_responsive,
)
from robotics_integration_tests.utilities.mqtt_recorder import MqttRecorder

# The broker user ISAR publishes as; granted `readwrite isar/#` by the broker's
# access_control file, which is also what the recorder needs in order to subscribe.
ISAR_MQTT_USERNAME = "isar"


def _pull_latest_images() -> None:
    """Pull the latest versions of all container images used by the integration tests.

    Images that are run with platform="linux/amd64" are pulled with the
    --platform flag so that Docker fetches the correct manifest on Apple
    Silicon hosts instead of silently falling back to a stale cached image.
    """
    amd64_images = [
        settings.FLOTILLA_BACKEND_IMAGE,
        settings.FLOTILLA_BROKER_IMAGE,
        settings.ISAR_ROBOT_IMAGE,
        settings.SARA_IMAGE,
    ]
    native_images = [
        settings.POSTGRESQL_IMAGE,
        settings.AZURITE_IMAGE,
        settings.KEYCLOAK_IMAGE,
    ]

    for image in amd64_images:
        logger.info(f"Pulling image (linux/amd64): {image}")
        result = subprocess.run(
            ["docker", "pull", "--platform", "linux/amd64", image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(f"Failed to pull {image}: {result.stderr.strip()}")
        else:
            logger.info(f"Successfully pulled {image}")

    for image in native_images:
        logger.info(f"Pulling image: {image}")
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(f"Failed to pull {image}: {result.stderr.strip()}")
        else:
            logger.info(f"Successfully pulled {image}")


@pytest.fixture(scope="session", autouse=True)
def pull_latest_images():
    _pull_latest_images()


@pytest.fixture
def test_id():
    return uuid.uuid4().hex[:8]


@pytest.fixture
def network():
    with Network() as network:
        yield network


@pytest.fixture
def keycloak(network: Network, test_id: str):
    """Local OpenID Connect issuer standing in for Azure Entra ID.

    The realm is imported from custom_realms/, the same file a developer mounts to
    run flotilla or sara against Keycloak locally, so a local run and a CI run
    exercise the same clients, scopes and roles.
    """
    container, issuer = create_keycloak_container(
        network=network,
        alias=settings.KEYCLOAK_ALIAS,
        port=settings.KEYCLOAK_PORT,
        test_id=test_id,
    )
    with container:
        wait_for_port_mapping_to_be_available(container=container, port=issuer.port)
        issuer.wait_until_ready()

        configure_issuer(issuer.host_url)
        try:
            yield issuer
        finally:
            reset_issuer()


@pytest.fixture
def flotilla_database(network: Network, test_id: str):
    with create_postgres_container(network, test_id=test_id) as database:
        wait_for_port_mapping_to_be_available(container=database, port=5432)
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
            test_id=test_id,
        ) as migrations_runner:
            # Block until the container exits; returns {"StatusCode": int}
            result = migrations_runner.get_wrapped_container().wait()
            status = int(result.get("StatusCode", 1))
            if status != 0:
                raise RuntimeError(f"Migrator failed with exit code {status}")

        logger.info("Migrations completed successfully (container exited cleanly)")

        yield FlotillaDatabase(
            database=database,
            connection_string=connection_string,
            alias=settings.DB_ALIAS,
        )


@pytest.fixture
def sara_database(network: Network, test_id: str):
    with create_sara_postgres_container(network, test_id=test_id) as database:
        wait_for_port_mapping_to_be_available(container=database, port=5432)
        logger.info(
            f"Postgres URL: {database.get_connection_url()}, "
            f"Port: {database.get_exposed_port(5432)}"
        )

        connection_string: str = (
            f"Host={settings.SARA_DB_ALIAS}; Port={5432}; Username={settings.SARA_DB_USER}; Password={settings.SARA_DB_PASSWORD}; "
            f"Database={settings.SARA_DB_ALIAS}; SSL Mode=Disable;"
        )

        with create_sara_migrations_runner_container(
            network=network,
            postgres_connection_string=connection_string,
            test_id=test_id,
        ) as migrations_runner:
            # Block until the container exits; returns {"StatusCode": int}
            result = migrations_runner.get_wrapped_container().wait()
            status = int(result.get("StatusCode", 1))
            if status != 0:
                raise RuntimeError(f"Sara migrator failed with exit code {status}")

        logger.info("Sara migrations completed successfully (container exited cleanly)")

        yield SaraDatabase(
            database=database,
            connection_string=connection_string,
            alias=settings.SARA_DB_ALIAS,
        )


@pytest.fixture
def armada_storage(network: Network, test_id: str):
    with ExitStack() as stack:
        azurite_containers: Dict[str, AzuriteStorageContainer] = {}

        for azurite_container_alias in settings.AZURITE_ALIASES:
            container: StreamLoggingDockerContainer = stack.enter_context(
                create_azurite_container(
                    network=network,
                    name=azurite_container_alias,
                    test_id=test_id,
                )
            )

            wait_for_port_mapping_to_be_available(container=container, port=10000)

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

            ensure_blob_containers(host_connection_string, "hua", "kaa", "nls", "test")

        yield ArmadaStorage(azurite_containers=azurite_containers)


@pytest.fixture
def flotilla_broker(network: Network, test_id: str):
    with create_flotilla_broker_container(
        network=network,
        image=settings.FLOTILLA_BROKER_IMAGE,
        name=settings.FLOTILLA_BROKER_NAME,
        port=settings.FLOTILLA_BROKER_PORT,
        alias=settings.FLOTILLA_BROKER_ALIAS,
        test_id=test_id,
    ) as broker:
        wait_for_port_mapping_to_be_available(
            container=broker, port=settings.FLOTILLA_BROKER_PORT
        )

        yield FlotillaBroker(
            broker=broker,
            name=settings.FLOTILLA_BROKER_NAME,
            port=settings.FLOTILLA_BROKER_PORT,
            alias=settings.FLOTILLA_BROKER_ALIAS,
        )


@pytest.fixture
def teams_webhook_receiver(network: Network, test_id: str):
    container, receiver = create_teams_webhook_receiver_container(
        network=network,
        test_id=test_id,
    )
    with container:
        wait_for_port_mapping_to_be_available(container=container, port=receiver.port)
        yield receiver


@pytest.fixture
def mqtt_recorder(flotilla_broker: FlotillaBroker):
    """Records every ISAR status and mission message published during a test.

    Ordered before the robot fixtures so that no transition is missed: ISAR
    republishes its status on every state machine iteration, and a recorder that
    attached late would silently lose the early states.
    """
    recorder = MqttRecorder(
        host="localhost",
        port=int(flotilla_broker.broker.get_exposed_port(flotilla_broker.port)),
        username=ISAR_MQTT_USERNAME,
        password=settings.ISAR_MQTT_PASSWORD,
    )
    recorder.start(flotilla_broker.broker)
    try:
        yield recorder
    finally:
        # Dump every trace on the way out. When an assertion about a transition
        # fails, the recorded traces are the only record of what the robots
        # actually did, and the ISAR container logs are gone by teardown.
        for robot_name in recorder.recorded_robot_names():
            logger.info(
                f"MQTT state trace for '{robot_name}': "
                f"{recorder.state_trace(robot_name)}"
            )
        recorder.stop()


@pytest.fixture
def flotilla_backend(
    network: Network,
    keycloak: Keycloak,
    flotilla_database: FlotillaDatabase,
    teams_webhook_receiver: TeamsWebhookReceiver,
    test_id: str,
):
    with create_flotilla_backend_container(
        network=network,
        keycloak=keycloak,
        database_connection_string=flotilla_database.connection_string,
        teams_notification_webhook_url=teams_webhook_receiver.internal_url,
        image=settings.FLOTILLA_BACKEND_IMAGE,
        name=settings.FLOTILLA_BACKEND_NAME,
        port=settings.FLOTILLA_BACKEND_PORT,
        alias=settings.FLOTILLA_BACKEND_ALIAS,
        test_id=test_id,
    ) as flotilla_backend:
        wait_for_port_mapping_to_be_available(
            container=flotilla_backend, port=settings.FLOTILLA_BACKEND_PORT
        )

        backend_url: str = f"http://localhost:{flotilla_backend.get_exposed_port(8000)}"
        wait_for_backend_to_be_responsive(backend_url=backend_url)
        assert_authentication_is_enforced(f"{backend_url}/robots")
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
def sara(
    network: Network,
    keycloak: Keycloak,
    sara_database: SaraDatabase,
    armada_storage: ArmadaStorage,
    test_id: str,
):
    with create_sara_container(
        network=network,
        keycloak=keycloak,
        database_connection_string=sara_database.connection_string,
        raw_storage_connection_string=armada_storage.azurite_containers[
            settings.SARA_RAW_STORAGE_CONTAINER
        ].docker_connection_string,
        image=settings.SARA_IMAGE,
        name=settings.SARA_NAME,
        port=settings.SARA_PORT,
        alias=settings.SARA_ALIAS,
        test_id=test_id,
    ) as sara_container:
        wait_for_port_mapping_to_be_available(
            container=sara_container, port=settings.SARA_PORT
        )

        sara_url: str = f"http://localhost:{sara_container.get_exposed_port(8100)}"
        wait_for_sara_to_be_responsive(sara_url=sara_url)
        assert_authentication_is_enforced(f"{sara_url}/api/analysis")

        yield Sara(
            sara=sara_container,
            backend_url=sara_url,
            name=settings.SARA_NAME,
            port=settings.SARA_PORT,
            alias=settings.SARA_ALIAS,
        )


@pytest.fixture
def armada_without_robots(
    network: Network,
    test_id: str,
    keycloak: Keycloak,
    flotilla_broker: FlotillaBroker,
    flotilla_database: FlotillaDatabase,
    flotilla_backend: FlotillaBackend,
    sara_database: SaraDatabase,
    sara: Sara,
    armada_storage: ArmadaStorage,
    teams_webhook_receiver: TeamsWebhookReceiver,
    mqtt_recorder: MqttRecorder,
):
    armada: Armada = Armada()

    armada.network = network
    armada.test_id = test_id
    armada.keycloak = keycloak
    armada.sara_database = sara_database
    armada.sara = sara
    armada.flotilla_database = flotilla_database
    armada.armada_storage = armada_storage
    armada.flotilla_broker = flotilla_broker
    armada.flotilla_backend = flotilla_backend
    armada.teams_webhook_receiver = teams_webhook_receiver
    armada.mqtt_recorder = mqtt_recorder

    yield armada


def _blob_connection_strings(armada: Armada) -> tuple[str, str]:
    """In-network Azurite connection strings for ISAR's data and metadata stores."""
    containers = armada.armada_storage.azurite_containers
    return (
        containers[settings.SARA_RAW_STORAGE_CONTAINER].docker_connection_string,
        containers[settings.SARA_ANON_STORAGE_CONTAINER].docker_connection_string,
    )


def _assert_robots_require_authentication(armada: Armada) -> None:
    """Confirm every ISAR robot rejects unauthenticated callers.

    An unauthenticated POST is refused before the handler runs, so this cannot
    disturb the robot's state machine.
    """
    for robot in armada.robots.values():
        assert_authentication_is_enforced(
            isar_url(robot, "/schedule/stop-mission"), method="POST"
        )


@pytest.fixture
def armada_with_single_successful_robot(armada_without_robots: Armada):
    armada: Armada = armada_without_robots
    blob_conn_data, blob_conn_metadata = _blob_connection_strings(armada)
    with create_isar_robot_container(
        network=armada.network,
        openid_config_url=armada.keycloak.internal_openid_config_url,
        image=settings.ISAR_ROBOT_IMAGE,
        name=settings.ISAR_ROBOT_NAME,
        port=settings.ISAR_ROBOT_PORT,
        alias=settings.ISAR_ROBOT_ALIAS,
        blob_storage_connection_string_data=blob_conn_data,
        blob_storage_connection_string_metadata=blob_conn_metadata,
        test_id=armada.test_id,
    ) as isar_robot:

        robot_id, installation_code_for_robot = setup_robot_in_flotilla(
            backend_url=armada.flotilla_backend.backend_url,
            robot_name=settings.ISAR_ROBOT_NAME,
        )

        armada.robots[settings.ISAR_ROBOT_NAME] = IsarRobot(
            container=isar_robot,
            name=settings.ISAR_ROBOT_NAME,
            robot_id=robot_id,
            port=settings.ISAR_ROBOT_PORT,
            alias=settings.ISAR_ROBOT_ALIAS,
            installation_code=installation_code_for_robot,
        )
        _assert_robots_require_authentication(armada)
        armada.log_startup_info()
        yield armada


@pytest.fixture
def armada_with_single_failing_robot(armada_without_robots: Armada):
    armada: Armada = armada_without_robots
    blob_conn_data, blob_conn_metadata = _blob_connection_strings(armada)

    with create_isar_robot_container(
        network=armada.network,
        openid_config_url=armada.keycloak.internal_openid_config_url,
        image=settings.ISAR_ROBOT_IMAGE,
        name=settings.ISAR_ROBOT_NAME,
        port=settings.ISAR_ROBOT_PORT,
        alias=settings.ISAR_ROBOT_ALIAS,
        blob_storage_connection_string_data=blob_conn_data,
        blob_storage_connection_string_metadata=blob_conn_metadata,
        should_fail_normal_task=True,
        test_id=armada.test_id,
    ) as isar_robot:

        robot_id, installation_code_for_robot = setup_robot_in_flotilla(
            backend_url=armada.flotilla_backend.backend_url,
            robot_name=settings.ISAR_ROBOT_NAME,
        )

        armada.robots[settings.ISAR_ROBOT_NAME] = IsarRobot(
            container=isar_robot,
            name=settings.ISAR_ROBOT_NAME,
            robot_id=robot_id,
            port=settings.ISAR_ROBOT_PORT,
            alias=settings.ISAR_ROBOT_ALIAS,
            installation_code=installation_code_for_robot,
        )
        _assert_robots_require_authentication(armada)
        armada.log_startup_info()
        yield armada


def _start_robot_roster(armada: Armada, roster, stack: ExitStack) -> Armada:
    """Start one ISAR container per scenario and register each with Flotilla.

    Shared by every multi-robot fixture so that adding a scenario is a matter of
    describing it, not of copying container plumbing.
    """
    blob_conn_data, blob_conn_metadata = _blob_connection_strings(armada)

    for scenario in roster:
        container = stack.enter_context(
            create_isar_robot_container(
                network=armada.network,
                openid_config_url=armada.keycloak.internal_openid_config_url,
                image=settings.ISAR_ROBOT_IMAGE,
                name=scenario.name,
                port=settings.ISAR_ROBOT_PORT,
                alias=scenario.alias,
                blob_storage_connection_string_data=blob_conn_data,
                blob_storage_connection_string_metadata=blob_conn_metadata,
                should_fail_normal_task=scenario.should_fail_normal_task,
                should_fail_return_home=scenario.should_fail_return_home,
                return_home_retry_limit=scenario.return_home_retry_limit,
                should_start_at_home=scenario.should_start_at_home,
                task_duration_in_seconds=scenario.task_duration_in_seconds,
                initial_battery_level=scenario.initial_battery_level,
                extra_environment=scenario.extra_environment,
                test_id=armada.test_id,
            )
        )

        wait_for_port_mapping_to_be_available(
            container=container, port=settings.ISAR_ROBOT_PORT
        )

        robot_id, installation_code = setup_robot_in_flotilla(
            backend_url=armada.flotilla_backend.backend_url,
            robot_name=scenario.name,
        )

        armada.robots[scenario.name] = IsarRobot(
            container=container,
            name=scenario.name,
            robot_id=robot_id,
            port=settings.ISAR_ROBOT_PORT,
            alias=scenario.alias,
            installation_code=installation_code,
        )

    _assert_robots_require_authentication(armada)
    armada.log_startup_info()
    return armada


@pytest.fixture
def armada_with_robot_roster(armada_without_robots: Armada):
    """Factory yielding an armada with an arbitrary roster of ISAR robots.

    Tests call it with a list of ``RobotScenario``. Every robot shares one stack,
    so several related scenarios can run in parallel for the price of one armada
    plus one container each.

    All robots default to ``should_start_at_home=True`` so they boot straight into
    ISAR's ``Home`` state. Without it the bootstrap return-home cycle races the
    test, and for robots configured to fail return-home it lands them in
    ``InterventionNeeded`` before a mission can be dispatched.
    """
    with ExitStack() as stack:

        def _start(roster) -> Armada:
            return _start_robot_roster(armada_without_robots, roster, stack)

        yield _start


@pytest.fixture
def armada_with_multiple_robots(armada_without_robots: Armada):
    """Four robots covering the mission/return-home outcome matrix.

    Robot configurations (mission and post-mission return-home outcomes):
        1. MissionOkThenHome – mission succeeds, returns home successfully
        2. MissionOkThenLost – mission succeeds, fails to return home
        3. MissionFailThenHome – mission fails, returns home successfully
        4. MissionFailThenLost – mission fails, fails to return home
    """
    roster = [
        RobotScenario(
            name="MissionOkThenHome",
            alias="isar_mission_ok_then_home",
        ),
        RobotScenario(
            name="MissionOkThenLost",
            alias="isar_mission_ok_then_lost",
            should_fail_return_home=True,
        ),
        RobotScenario(
            name="MissionFailThenHome",
            alias="isar_mission_fail_then_home",
            should_fail_normal_task=True,
        ),
        RobotScenario(
            name="MissionFailThenLost",
            alias="isar_mission_fail_then_lost",
            should_fail_normal_task=True,
            should_fail_return_home=True,
        ),
    ]

    with ExitStack() as stack:
        yield _start_robot_roster(armada_without_robots, roster, stack)


def wait_for_port_mapping_to_be_available(
    container: DockerContainer, port: int, timeout: int = 60, delay: int = 2
) -> None:
    now: datetime = datetime.now()
    while (datetime.now() - now).seconds < timeout:
        try:
            container.get_exposed_port(port)
            return
        except ConnectionError:
            logger.warning(
                f"Port {port} not yet available, waiting for {delay} seconds..."
            )
            time.sleep(delay)
            continue

    raise ConnectionError(
        f"Port mapping for container {container.image} on port {port} not available within timeout"
    )
