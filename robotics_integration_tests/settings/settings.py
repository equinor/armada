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

    # The clients used to mint tokens are properties of the realm file, not
    # configuration, so they live in custom_containers/keycloak.py. Deliberately
    # not settings: an INTEGRATION_TESTS_CLIENT_SECRET setting would be silently
    # overridden by the stale Entra value of that name still sitting in many
    # developers' .env files and in every consuming repository's secrets.

    # Audiences validated by each service. Plain readable names rather than Entra
    # app registration GUIDs.
    FLOTILLA_AUDIENCE: str = Field(default="flotilla-test")
    ISAR_AUDIENCE: str = Field(default="isar-test")
    SARA_AUDIENCE: str = Field(default="sara-test")

    # Client scopes requested when minting a token. Unlike Entra, Keycloak does
    # not derive the audience from the scope: each of these carries a single
    # audience mapper onto the matching *_AUDIENCE above. Request exactly one per
    # token -- two audience mappers make Keycloak emit `aud` as an array, and
    # ISAR's token model accepts only the string form.
    FLOTILLA_SCOPE: str = Field(default="flotilla-api")
    ISAR_SCOPE: str = Field(default="isar-api")
    SARA_SCOPE: str = Field(default="sara-api")

    # Flotilla Backend environment
    MQTT_HOST: str = Field(default="broker")
    # MQTT authentication is username/password, validated by the broker against
    # the hashed passwd_file committed in equinor/flotilla. It is deliberately out
    # of scope for this work, so these remain real secrets supplied via
    # the environment or a local .env.
    FLOTILLA_MQTT_PASSWORD: str = Field(default="")
    # Selects appsettings.IntegrationTest.json in flotilla and sara, which sets
    # Authentication:Provider=Oidc, points token validation at the realm above and
    # disables Key Vault and Redis.
    ASPNETCORE_ENVIRONMENT: str = Field(default="IntegrationTest")
    FLOTILLA_BACKEND_NAME: str = Field(default="flotilla_backend")
    FLOTILLA_BACKEND_ALIAS: str = Field(default="flotilla_backend")
    FLOTILLA_BACKEND_IMAGE: str = Field(
        default="ghcr.io/equinor/flotilla-backend:latest"
    )
    FLOTILLA_BACKEND_PORT: int = Field(default=8000)

    # MQTT Broker environment
    # TLS private key for the test broker; see the note on FLOTILLA_MQTT_PASSWORD.
    FLOTILLA_BROKER_SERVER_KEY: str = Field(default="")
    FLOTILLA_BROKER_NAME: str = Field(default="flotilla_broker")
    FLOTILLA_BROKER_ALIAS: str = Field(default="broker")
    FLOTILLA_BROKER_IMAGE: str = Field(default="ghcr.io/equinor/flotilla-broker:latest")
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
    ISAR_MQTT_PASSWORD: str = Field(default="")
    ISAR_ROBOT_NAME: str = Field(default="Placebot")
    ISAR_ROBOT_ALIAS: str = Field(default="isar_robot")
    ISAR_ROBOT_IMAGE: str = Field(default="ghcr.io/equinor/isar-robot:latest")
    ISAR_ROBOT_PORT: int = Field(default=3000)

    # SARA environment and configuration
    SARA_RAW_STORAGE_CONTAINER: str = Field(default="sara-raw")
    SARA_ANON_STORAGE_CONTAINER: str = Field(default="sara-anon")
    SARA_VIS_STORAGE_CONTAINER: str = Field(default="sara-vis")
    SARA_IMAGE: str = Field(default="ghcr.io/equinor/sara:latest")
    SARA_NAME: str = Field(default="sara")
    SARA_PORT: int = Field(default=8100)
    SARA_ALIAS: str = Field(default="sara")
    SARA_MQTT_PASSWORD: str = Field(default="")

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
