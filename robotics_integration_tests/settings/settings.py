from typing import Optional, List

from dotenv import load_dotenv
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Integration test app registration
    INTEGRATION_TESTS_CLIENT_ID: str = Field(
        default="17d7c036-e4ff-4df6-87fd-0d648a36a727"
    )
    INTEGRATION_TESTS_TENANT_ID: str = Field(
        default="3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
    )
    INTEGRATION_TESTS_CLIENT_SECRET: Optional[str] = Field(default="")

    # Keyvault configuration (using Flotilla service principle)
    KEYVAULT_NAME: str = Field(default="FlotillaTestsKv")

    @computed_field
    @property
    def KEYVAULT_URI(self) -> str:
        return f"https://{self.KEYVAULT_NAME.lower()}.vault.azure.net"

    # Flotilla Backend environment
    MQTT_HOST: str = Field(default="broker")
    FLOTILLA_MQTT_PASSWORD: Optional[str] = Field(default="")
    ASPNETCORE_ENVIRONMENT: str = Field(default="Development")
    FLOTILLA_AZURE_CLIENT_SECRET: Optional[str] = Field(default="")
    FLOTILLA_AZURE_CLIENT_ID: Optional[str] = Field(
        default="ea4c7b92-47b3-45fb-bd25-a8070f0c495c"
    )
    AZURE_TENANT_ID: Optional[str] = Field(
        default="3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
    )
    FLOTILLA_BACKEND_NAME: str = Field(default="flotilla_backend")
    FLOTILLA_BACKEND_ALIAS: str = Field(default="flotilla_backend")
    FLOTILLA_BACKEND_IMAGE: str = Field(
        default="ghcr.io/equinor/flotilla-backend:latest"
    )
    FLOTILLA_BACKEND_PORT: int = Field(default=8000)

    # MQTT Broker environment
    FLOTILLA_BROKER_SERVER_KEY: Optional[str] = Field(default="")
    FLOTILLA_BROKER_NAME: str = Field(default="flotilla_broker")
    FLOTILLA_BROKER_ALIAS: str = Field(default="broker")
    FLOTILLA_BROKER_IMAGE: str = Field(default="ghcr.io/equinor/flotilla-broker:latest")
    FLOTILLA_BROKER_PORT: int = Field(default=1883)

    # PostgreSQL Database environment
    POSTGRESQL_IMAGE: str = Field(default="postgres:16")
    DB_USER: str = Field(default="flotilla")
    DB_PASSWORD: str = Field(default="default_password")
    DB_ALIAS: str = Field(default="postgres_database")

    GIT_REPOSITORY_FOR_MIGRATIONS: str = Field(default="equinor/flotilla")
    GIT_REPOSITORY_FOR_MIGRATIONS_REF: str = Field(default="latest")
    BACKEND_PROJECT_FILE_FOLDER: str = Field(default="backend/api")

    # Migrations runner environment
    RELATIVE_PATH_TO_DOCKERFILE: str = Field(
        default="./robotics_integration_tests/custom_images/migrations_runner/"
    )

    # ISAR Robot environment
    ISAR_AZURE_CLIENT_SECRET: Optional[str] = Field(default="")
    ISAR_MQTT_PASSWORD: Optional[str] = Field(default="")
    ISAR_AZURE_CLIENT_ID: Optional[str] = Field(
        default="fd384acd-5c1b-4c44-a1ac-d41d720ed0fe"
    )
    ISAR_AZURE_TENANT_ID: Optional[str] = Field(
        default="3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
    )
    ISAR_ROBOT_NAME: str = Field(default="Placebot")
    ISAR_ROBOT_ALIAS: str = Field(default="isar_robot")
    ISAR_ROBOT_IMAGE: str = Field(default="ghcr.io/equinor/isar-robot:latest")
    ISAR_ROBOT_PORT: int = Field(default=3000)

    # SARA environment and configuration
    SARA_RAW_STORAGE_CONTAINER: str = Field(default="sara-raw")
    SARA_ANON_STORAGE_CONTAINER: str = Field(default="sara-anon")
    SARA_VIS_STORAGE_CONTAINER: str = Field(default="sara-vis")

    # Azurite environment and configurations
    AZURITE_IMAGE: str = Field(default="mcr.microsoft.com/azure-storage/azurite:latest")

    @computed_field
    @property
    def AZURITE_ALIASES(self) -> List[str]:
        return [
            self.SARA_RAW_STORAGE_CONTAINER,
            self.SARA_ANON_STORAGE_CONTAINER,
            self.SARA_VIS_STORAGE_CONTAINER,
        ]

    AZURITE_ACCOUNT: str = Field(default="devstoreaccount1")
    AZURITE_KEY: str = Field(
        default="Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
    )  # This is a default Azurite key for a development container and not a secret

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


load_dotenv()
settings = Settings()
