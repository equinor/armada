import uuid

from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


class IsarRobot:
    def __init__(
        self,
        container: StreamLoggingDockerContainer,
        name: str,
        robot_id: str,
        port: int,
        alias: str,
        installation_code: str,
    ) -> None:
        self.container: StreamLoggingDockerContainer = container
        self.name: str = name
        self.robot_id: str = robot_id
        self.port: int = port
        self.alias: str = alias
        self.installation_code: str = installation_code


def create_isar_robot_container(
    network: Network,
    openid_config_url: str,
    image: str = "ghcr.io/equinor/isar-robot:latest",
    name: str = "isar_robot",
    port: int = 3000,
    alias: str = "isar_robot",
    blob_storage_connection_string_data: str = "",
    blob_storage_connection_string_metadata: str = "",
    should_fail_normal_task: bool = False,
    should_fail_return_home: bool = False,
    return_home_retry_limit: int = 5,
    should_start_at_home: bool = False,
    mission_battery_start_threshold: float | None = None,
    battery_poll_interval: float | None = None,
    task_duration: float | None = None,
    test_id: str = "",
) -> StreamLoggingDockerContainer:

    failure_prob = 0.0
    if should_fail_normal_task:
        failure_prob = 1.0

    return_home_failure_prob = 0.0
    if should_fail_return_home:
        return_home_failure_prob = 1.0

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(f"{name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(alias)
        .with_kwargs(platform="linux/amd64")
        .with_env("ISAR_MQTT_HOST", settings.FLOTILLA_BROKER_ALIAS)
        .with_env("ISAR_MQTT_PASSWORD", settings.ISAR_MQTT_PASSWORD)
        # ISAR_AZURE_CLIENT_ID is the expected `aud`. settings.py lets a bare
        # AZURE_CLIENT_ID override it, so that variable must not be set here.
        .with_env("ISAR_OPENID_CONFIG_URL", openid_config_url)
        .with_env("ISAR_AZURE_CLIENT_ID", settings.ISAR_AUDIENCE)
        .with_env("ISAR_STORAGE_BLOB_ENABLED", "true")
        .with_env("ISAR_BLOB_STORAGE_ACCOUNT_DATA", settings.AZURITE_ACCOUNT)
        .with_env(
            "ISAR_BLOB_STORAGE_CONNECTION_STRING_DATA",
            blob_storage_connection_string_data,
        )
        .with_env("ISAR_BLOB_STORAGE_ACCOUNT_METADATA", settings.AZURITE_ACCOUNT)
        .with_env(
            "ISAR_BLOB_STORAGE_CONNECTION_STRING_METADATA",
            blob_storage_connection_string_metadata,
        )
        .with_env("ISAR_BLOB_CONTAINER", "hua")
        .with_env("ISAR_PLANT_CODE", "Huldra")
        .with_env("ISAR_PLANT_SHORT_NAME", "HUA")
        .with_env("ISAR_API_HOST_VIEWED_EXTERNALLY", alias)
        .with_env("ISAR_ROBOT_NAME", name)
        .with_env("MISSION_SIMULATION_TIME_TO_START", 2)
        .with_env("ROBOT_MISSION_SIMULATION_TASK_FAILURE_PROBABILITY", failure_prob)
        .with_env(
            "ROBOT_MISSION_SIMULATION_RETURN_HOME_TASK_FAILURE_PROBABILITY",
            return_home_failure_prob,
        )
        .with_env("ROBOT_MISSION_SIMULATION_MISSION_COMPLETION_DELAY", 5)
        .with_env("ISAR_RETURN_HOME_RETRY_LIMIT", return_home_retry_limit)
        .with_env("ROBOT_SHOULD_START_AT_HOME", str(should_start_at_home).lower())
        .with_env("ISAR_ISAR_ID", str(uuid.uuid4()))
    )

    # isar-robot starts at 75% battery and discharges on every battery telemetry
    # tick. Raising the threshold above the starting level is what makes ISAR
    # decide the robot must recharge; without it the recharge states are
    # unreachable in a test-length run.
    if mission_battery_start_threshold is not None:
        container = container.with_env(
            "ISAR_ROBOT_MISSION_BATTERY_START_THRESHOLD",
            mission_battery_start_threshold,
        )
    if battery_poll_interval is not None:
        container = container.with_env(
            "ISAR_ROBOT_API_BATTERY_POLL_INTERVAL", battery_poll_interval
        )
    if task_duration is not None:
        container = container.with_env(
            "ROBOT_MISSION_SIMULATION_TASK_DURATION", task_duration
        )

    return container
