from typing import Dict

from robotics_integration_tests.custom_containers.sara import Sara
from robotics_integration_tests.settings.settings import settings
from testcontainers.core.network import Network
from loguru import logger
from robotics_integration_tests.custom_containers.azurite import FlotillaStorage
from robotics_integration_tests.custom_containers.flotilla_backend import (
    FlotillaBackend,
)
from robotics_integration_tests.custom_containers.isar import IsarRobot
from robotics_integration_tests.custom_containers.mosquitto import FlotillaBroker
from robotics_integration_tests.custom_containers.postgres import (
    FlotillaDatabase,
    SaraDatabase,
)
from robotics_integration_tests.utilities.keyvault import Keyvault


class Armada:
    def __init__(self) -> None:
        self.network: Network | None = None
        self.keyvault: Keyvault | None = None
        self.flotilla_database: FlotillaDatabase | None = None
        self.flotilla_broker: FlotillaBroker | None = None
        self.flotilla_backend: FlotillaBackend | None = None
        self.flotilla_storage: FlotillaStorage | None = None
        self.sara: Sara | None = None
        self.sara_database: SaraDatabase | None = None
        self.robots: Dict[str, IsarRobot] = {}

    def log_startup_info(self) -> None:
        logger.info("Armada has been deployed")
        logger.info(
            f"Broker exposed port is {self.flotilla_broker.broker.get_exposed_port(1883)}"
        )
        logger.info(
            f"Backend exposed port is {self.flotilla_backend.container.get_exposed_port(8000)}"
        )
        logger.info(
            f"ISAR Robot exposed port is {self.robots[settings.ISAR_ROBOT_NAME].container.get_exposed_port(3000)}"
        )
        logger.info(
            f"Sara exposed port is {self.sara.container.get_exposed_port(8100)}"
        )
