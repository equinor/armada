from typing import List

from dotenv import load_dotenv
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Local Keycloak realm standing in for Azure Entra ID. See
    # custom_realms/robotics-realm.json for the clients, scopes and roles.
    KEYCLOAK_IMAGE: str = Field(default="quay.io/keycloak/keycloak:26.4")
    KEYCLOAK_ALIAS: str = Field(default="keycloak")
    KEYCLOAK_PORT: int = Field(default=8080)
    KEYCLOAK_REALM: str = Field(default="robotics")

    # The test clients live in custom_containers/keycloak.py, not here: an
    # INTEGRATION_TESTS_CLIENT_SECRET setting would be silently overridden by the
    # stale Entra value of that name still sitting in .env files and repo secrets.

    # Fixture value from the realm, not a secret.
    FLOTILLA_CLIENT_SECRET: str = Field(default="flotilla-test-secret")

    # Audiences validated by each service.
    FLOTILLA_AUDIENCE: str = Field(default="flotilla-test")
    ISAR_AUDIENCE: str = Field(default="isar-test")
    SARA_AUDIENCE: str = Field(default="sara-test")

    # Each carries a single audience mapper onto the matching *_AUDIENCE above.
    # Request exactly one per token: two make Keycloak emit `aud` as an array,
    # which ISAR rejects.
    FLOTILLA_SCOPE: str = Field(default="flotilla-api")
    ISAR_SCOPE: str = Field(default="isar-api")
    SARA_SCOPE: str = Field(default="sara-api")

    # Flotilla Backend environment
    MQTT_HOST: str = Field(default="broker")
    # Has no appsettings file in flotilla or sara: the name only makes them accept
    # a plain-HTTP authority. Everything else is passed from custom_containers/.
    ASPNETCORE_ENVIRONMENT: str = Field(default="IntegrationTest")
    FLOTILLA_BACKEND_NAME: str = Field(default="flotilla_backend")
    FLOTILLA_BACKEND_ALIAS: str = Field(default="flotilla_backend")
    # The service images are published to ghcr.io as public packages. :latest is
    # the newest release, :dev the last push to main. Being public, a local run
    # needs no registry login at all.
    FLOTILLA_BACKEND_IMAGE: str = Field(
        default="ghcr.io/equinor/flotilla-backend:latest"
    )
    FLOTILLA_BACKEND_PORT: int = Field(default=8000)

    # MQTT Broker environment
    # Credentials are generated per run; see utilities/mqtt_credentials.py. The
    # certificate is issued for FLOTILLA_BROKER_ALIAS, which ISAR verifies.
    FLOTILLA_BROKER_NAME: str = Field(default="flotilla_broker")
    FLOTILLA_BROKER_ALIAS: str = Field(default="broker")
    FLOTILLA_BROKER_IMAGE: str = Field(
        default="ghcr.io/equinor/flotilla-broker:latest"
    )
    FLOTILLA_BROKER_PORT: int = Field(default=1883)

    # PostgreSQL Flotilla Database environment
    POSTGRESQL_IMAGE: str = Field(default="postgres:16")
    DB_USER: str = Field(default="flotilla")
    DB_PASSWORD: str = Field(default="default_password")
    DB_ALIAS: str = Field(default="flotilla_postgres_database")

    GIT_REPOSITORY_FOR_MIGRATIONS: str = Field(default="equinor/flotilla")
    GIT_REPOSITORY_FOR_MIGRATIONS_REF: str = Field(default="latest")
    BACKEND_PROJECT_FILE_FOLDER: str = Field(default="backend/api")

    # Path to a local flotilla checkout to take migrations from. When set, it
    # takes precedence over cloning GIT_REPOSITORY_FOR_MIGRATIONS from GitHub, and
    # GIT_REPOSITORY_FOR_MIGRATIONS_REF is ignored. Use this together with locally
    # built images (see scripts/build_local_images.sh) so that the schema and the
    # application code come from the same source. Uncommitted and untracked
    # migrations are included, since the directory is copied rather than cloned.
    FLOTILLA_MIGRATIONS_SOURCE_DIR: str = Field(default="")

    # PostgreSQL Sara Database environment
    POSTGRESQL_IMAGE: str = Field(default="postgres:16")
    SARA_DB_USER: str = Field(default="sara")
    SARA_DB_PASSWORD: str = Field(default="default_password")
    SARA_DB_ALIAS: str = Field(default="sara_postgres_database")

    SARA_GIT_REPOSITORY_FOR_MIGRATIONS: str = Field(default="equinor/sara")
    SARA_GIT_REPOSITORY_FOR_MIGRATIONS_REF: str = Field(default="latest")

    SARA_BACKEND_PROJECT_FILE_FOLDER: str = Field(default="api")

    # See FLOTILLA_MIGRATIONS_SOURCE_DIR.
    SARA_MIGRATIONS_SOURCE_DIR: str = Field(default="")

    # Migrations runner environment
    RELATIVE_PATH_TO_DOCKERFILE: str = Field(
        default="./robotics_integration_tests/custom_images/migrations_runner/"
    )

    # ISAR Robot environment
    ISAR_ROBOT_NAME: str = Field(default="Placebot")
    ISAR_ROBOT_ALIAS: str = Field(default="isar_robot")
    ISAR_ROBOT_IMAGE: str = Field(
        default="ghcr.io/equinor/isar-robot:latest"
    )
    ISAR_ROBOT_PORT: int = Field(default=3000)

    # SARA environment and configuration
    SARA_RAW_STORAGE_CONTAINER: str = Field(default="sara-raw")
    SARA_ANON_STORAGE_CONTAINER: str = Field(default="sara-anon")
    SARA_VIS_STORAGE_CONTAINER: str = Field(default="sara-vis")
    SARA_IMAGE: str = Field(
        default="ghcr.io/equinor/sara:latest"
    )
    SARA_NAME: str = Field(default="sara")
    SARA_PORT: int = Field(default=8100)
    SARA_ALIAS: str = Field(default="sara")

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

    AZURITE_ACCOUNT: str = Field(default="saradevstorageraw")
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
