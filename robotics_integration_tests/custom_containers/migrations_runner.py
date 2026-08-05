from pathlib import Path

from docker.models.networks import Network
from loguru import logger

from robotics_integration_tests.custom_containers.image_builder import build_image_once
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings

# Where a local checkout is mounted inside the migrations runner.
_LOCAL_REPO_MOUNT = "/src"


def _with_migrations_source(
    container: StreamLoggingDockerContainer,
    source_dir: str,
    project_folder: str,
    setting_name: str,
) -> StreamLoggingDockerContainer:
    """Take migrations from a local checkout instead of cloning from GitHub.

    Mounted read-only; the entrypoint copies it into the container so that nothing
    can be written back into the working tree. The copy means uncommitted and
    untracked migrations are picked up, which is the reason to use this at all.

    Validation is deliberately strict and happens here, before the container
    starts: silently falling back to the GitHub clone would leave you believing
    you had tested a local migration when you had not.
    """
    if not source_dir:
        return container

    resolved: Path = Path(source_dir).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(
            f"{setting_name} is set to '{source_dir}' (resolved to '{resolved}'), "
            "which is not a directory."
        )

    project_dir: Path = resolved / project_folder
    if not list(project_dir.glob("*.csproj")):
        raise ValueError(
            f"{setting_name} is set to '{resolved}', but no .csproj was found in "
            f"'{project_dir}'. Point it at the repository root of the service, not "
            "at the project folder."
        )

    logger.info(f"Using migrations from local checkout: {resolved}")
    return container.with_volume_mapping(
        str(resolved), _LOCAL_REPO_MOUNT, "ro"
    ).with_env("LOCAL_REPO_PATH", _LOCAL_REPO_MOUNT)


def _with_design_time_database_config(
    container: StreamLoggingDockerContainer, postgres_connection_string: str
) -> StreamLoggingDockerContainer:
    """Supply the connection string to EF's design-time context factory.

    ``dotnet ef database update --connection`` overrides the connection used for
    the migration itself, but EF still instantiates ``DesignTimeContextFactory``,
    which reads its own configuration and falls back to **Azure Key Vault** when
    no connection string is present. Passing it as configuration short-circuits
    that fallback, which is what removes the Key Vault dependency here.

    Flotilla and sara read different keys for this (``PostgreSqlConnectionString``
    vs ``postgresConnectionString``), so both are set.
    """
    return (
        container.with_env(
            "Database__postgresConnectionString", postgres_connection_string
        )
        .with_env("Database__PostgreSqlConnectionString", postgres_connection_string)
        .with_env("Database__ConnectionString", postgres_connection_string)
        .with_env("Database__AllowedAuthMethods__0", "ConnectionString")
    )


def create_migrations_runner_container(
    network: Network,
    postgres_connection_string: str,
    name: str = "flotilla_migrations",
    test_id: str = "",
) -> StreamLoggingDockerContainer:
    migrations_runner_image: str = build_image_once(
        path=str(Path(settings.RELATIVE_PATH_TO_DOCKERFILE).resolve(strict=True)),
        tag="flotilla-migrations-runner",
    )

    container = (
        StreamLoggingDockerContainer(image=migrations_runner_image)
        .with_name(f"{name}-{test_id}")
        .with_network(network)
        .with_env("DATABASE_URL", postgres_connection_string)
        .with_env("GIT_REPO", settings.GIT_REPOSITORY_FOR_MIGRATIONS)
        .with_env("GIT_REF", settings.GIT_REPOSITORY_FOR_MIGRATIONS_REF)
        .with_env("EF_PROJECT_PATH", settings.BACKEND_PROJECT_FILE_FOLDER)
        .with_env("EF_STARTUP_PATH", settings.BACKEND_PROJECT_FILE_FOLDER)
    )
    container = _with_migrations_source(
        container,
        source_dir=settings.FLOTILLA_MIGRATIONS_SOURCE_DIR,
        project_folder=settings.BACKEND_PROJECT_FILE_FOLDER,
        setting_name="FLOTILLA_MIGRATIONS_SOURCE_DIR",
    )
    return _with_design_time_database_config(container, postgres_connection_string)


def create_sara_migrations_runner_container(
    network: Network,
    postgres_connection_string: str,
    name: str = "sara_migrations",
    test_id: str = "",
) -> StreamLoggingDockerContainer:
    sara_migrations_runner_image: str = build_image_once(
        path=str(Path(settings.RELATIVE_PATH_TO_DOCKERFILE).resolve(strict=True)),
        tag="sara-migrations-runner",
    )

    container = (
        StreamLoggingDockerContainer(image=sara_migrations_runner_image)
        .with_name(f"{name}-{test_id}")
        .with_network(network)
        .with_env("DATABASE_URL", postgres_connection_string)
        .with_env("GIT_REPO", settings.SARA_GIT_REPOSITORY_FOR_MIGRATIONS)
        .with_env("GIT_REF", settings.SARA_GIT_REPOSITORY_FOR_MIGRATIONS_REF)
        .with_env("EF_PROJECT_PATH", settings.SARA_BACKEND_PROJECT_FILE_FOLDER)
        .with_env("EF_STARTUP_PATH", settings.SARA_BACKEND_PROJECT_FILE_FOLDER)
    )
    container = _with_migrations_source(
        container,
        source_dir=settings.SARA_MIGRATIONS_SOURCE_DIR,
        project_folder=settings.SARA_BACKEND_PROJECT_FILE_FOLDER,
        setting_name="SARA_MIGRATIONS_SOURCE_DIR",
    )
    return _with_design_time_database_config(container, postgres_connection_string)
