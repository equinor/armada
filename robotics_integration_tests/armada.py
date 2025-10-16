from typing import Dict

from testcontainers.core.network import Network

from robotics_integration_tests.custom_containers.azurite import FlotillaStorage
from robotics_integration_tests.custom_containers.flotilla_backend import (
    FlotillaBackend,
)
from robotics_integration_tests.custom_containers.isar import IsarRobot
from robotics_integration_tests.custom_containers.mosquitto import FlotillaBroker
from robotics_integration_tests.custom_containers.postgres import FlotillaDatabase
from robotics_integration_tests.utilities.keyvault import Keyvault


class Armada:
    def __init__(self) -> None:
        self.network: Network | None = None
        self.keyvault: Keyvault | None = None
        self.flotilla_database: FlotillaDatabase | None = None
        self.flotilla_broker: FlotillaBroker | None = None
        self.flotilla_backend: FlotillaBackend | None = None
        self.flotilla_storage: FlotillaStorage | None = None
        self.robots: Dict[str, IsarRobot] = {}
