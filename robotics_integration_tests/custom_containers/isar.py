import json
import re
import uuid
from dataclasses import dataclass

from docker.models.networks import Network

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.mqtt_credentials import MqttCredentials


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


@dataclass(frozen=True)
class Plant:
    """A plant seeded by populate_database_with_minimum_models."""

    installation_code: str
    name: str

    @property
    def blob_container(self) -> str:
        return self.installation_code.lower()


HULDRA = Plant(installation_code="HUA", name="Huldra")
KAARSTO = Plant(installation_code="KAA", name="Kårstø")


@dataclass
class RobotConfig:
    """Everything that makes one ISAR robot differ from another.

    Every value is sent to the robot.
    """

    name: str
    alias: str = ""
    should_fail_normal_task: bool = False
    should_fail_return_home: bool = False
    should_start_at_home: bool = False
    return_home_retry_limit: int = 5
    task_duration_in_seconds: float = 5.0
    initial_battery_level: float = 75.0
    return_home_delay_in_seconds: int = 10
    mission_battery_start_threshold: float = 25.0
    battery_recharge_threshold: float = 80.0
    battery_publish_interval_in_seconds: float = 2.0
    battery_poll_interval_in_seconds: float = 5.0
    plant: Plant = HULDRA

    def __post_init__(self) -> None:
        if not self.alias:
            snake_case_name: str = re.sub(r"(?<!^)(?=[A-Z])", "_", self.name).lower()
            self.alias = f"isar_{snake_case_name}"


def create_isar_robot_container(
    network: Network,
    openid_config_url: str,
    mqtt_credentials: MqttCredentials,
    config: RobotConfig,
    image: str = "ghcr.io/equinor/isar-robot:latest",
    port: int = 3000,
    blob_storage_connection_string_data: str = "",
    blob_storage_connection_string_metadata: str = "",
    test_id: str = "",
) -> StreamLoggingDockerContainer:

    failure_prob = 1.0 if config.should_fail_normal_task else 0.0
    return_home_failure_prob = 1.0 if config.should_fail_return_home else 0.0

    container: StreamLoggingDockerContainer = (
        StreamLoggingDockerContainer(image=image)
        .with_name(f"{config.name}-{test_id}")
        .with_exposed_ports(port)
        .with_network(network)
        .with_network_aliases(config.alias)
        .with_kwargs(platform="linux/amd64")
        .with_env("ISAR_MQTT_HOST", settings.FLOTILLA_BROKER_ALIAS)
        .with_env("ISAR_MQTT_PASSWORD", mqtt_credentials.passwords["isar"])
        # ISAR verifies the broker certificate against this, not the bundled CA.
        .with_env("ISAR_MQTT_CA_CERT", mqtt_credentials.ca_certificate)
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
        .with_env("ISAR_BLOB_CONTAINER", config.plant.blob_container)
        .with_env("ISAR_PLANT_CODE", config.plant.name)
        .with_env("ISAR_PLANT_SHORT_NAME", config.plant.installation_code)
        .with_env("ISAR_API_HOST_VIEWED_EXTERNALLY", config.alias)
        .with_env("ISAR_API_PORT", port)
        .with_env("ISAR_ROBOT_NAME", config.name)
        .with_env("ISAR_SERIAL_NUMBER", "0001")
        .with_env("ISAR_DOCUMENTATION", "[]")
        .with_env("ROBOT_MODEL", "Robot")
        .with_env(
            "CAPABILITIES",
            json.dumps(
                [
                    "take_thermal_image",
                    "take_image",
                    "take_video",
                    "take_thermal_video",
                    "record_audio",
                    "take_co2_measurement",
                    "take_acoustic_measurement",
                ]
            ),
        )
        .with_env("MISSION_SIMULATION_TIME_TO_START", 2)
        .with_env("ROBOT_MISSION_SIMULATION_TASK_FAILURE_PROBABILITY", failure_prob)
        .with_env(
            "ROBOT_MISSION_SIMULATION_RETURN_HOME_TASK_FAILURE_PROBABILITY",
            return_home_failure_prob,
        )
        .with_env("ROBOT_MISSION_SIMULATION_MISSION_COMPLETION_DELAY", 5)
        .with_env("ISAR_RETURN_HOME_RETRY_LIMIT", config.return_home_retry_limit)
        .with_env(
            "ROBOT_SHOULD_START_AT_HOME", str(config.should_start_at_home).lower()
        )
        .with_env("ISAR_ISAR_ID", str(uuid.uuid4()))
        .with_env(
            "ROBOT_MISSION_SIMULATION_TASK_DURATION", config.task_duration_in_seconds
        )
        .with_env("ROBOT_INITIAL_BATTERY_LEVEL", config.initial_battery_level)
        .with_env("ISAR_RETURN_HOME_DELAY", config.return_home_delay_in_seconds)
        .with_env(
            "ISAR_ROBOT_MISSION_BATTERY_START_THRESHOLD",
            config.mission_battery_start_threshold,
        )
        .with_env(
            "ISAR_ROBOT_BATTERY_RECHARGE_THRESHOLD", config.battery_recharge_threshold
        )
        .with_env(
            "ROBOT_ROBOT_BATTERY_PUBLISH_INTERVAL",
            config.battery_publish_interval_in_seconds,
        )
        .with_env(
            "ISAR_ROBOT_API_BATTERY_POLL_INTERVAL",
            config.battery_poll_interval_in_seconds,
        )
    )

    return container
