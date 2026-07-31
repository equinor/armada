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


def create_migrations_runner_container(
    network: Network, postgres_connection_string: str, name: str = "flotilla_migrations", test_id: str = ""
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
        .with_env("AZURE_CLIENT_SECRET", settings.FLOTILLA_AZURE_CLIENT_SECRET)
        .with_env("AZURE_CLIENT_ID", settings.FLOTILLA_AZURE_CLIENT_ID)
        .with_env("AZURE_TENANT_ID", settings.AZURE_TENANT_ID)
        .with_env("GIT_REPO", settings.GIT_REPOSITORY_FOR_MIGRATIONS)
        .with_env("GIT_REF", settings.GIT_REPOSITORY_FOR_MIGRATIONS_REF)
        .with_env("EF_PROJECT_PATH", settings.BACKEND_PROJECT_FILE_FOLDER)
        .with_env("EF_STARTUP_PATH", settings.BACKEND_PROJECT_FILE_FOLDER)
    )
    return _with_migrations_source(
        container,
        source_dir=settings.FLOTILLA_MIGRATIONS_SOURCE_DIR,
        project_folder=settings.BACKEND_PROJECT_FILE_FOLDER,
        setting_name="FLOTILLA_MIGRATIONS_SOURCE_DIR",
    )


def create_sara_migrations_runner_container(
    network: Network, postgres_connection_string: str, name: str = "sara_migrations", test_id: str = ""
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
        .with_env("AZURE_CLIENT_SECRET", settings.SARA_AZURE_CLIENT_SECRET)
        .with_env("AZURE_CLIENT_ID", settings.SARA_AZURE_CLIENT_ID)
        .with_env("AZURE_TENANT_ID", settings.SARA_AZURE_TENANT_ID)
        .with_env("GIT_REPO", settings.SARA_GIT_REPOSITORY_FOR_MIGRATIONS)
        .with_env("GIT_REF", settings.SARA_GIT_REPOSITORY_FOR_MIGRATIONS_REF)
        .with_env("EF_PROJECT_PATH", settings.SARA_BACKEND_PROJECT_FILE_FOLDER)
        .with_env("EF_STARTUP_PATH", settings.SARA_BACKEND_PROJECT_FILE_FOLDER)
    )
    return _with_migrations_source(
        container,
        source_dir=settings.SARA_MIGRATIONS_SOURCE_DIR,
        project_folder=settings.SARA_BACKEND_PROJECT_FILE_FOLDER,
        setting_name="SARA_MIGRATIONS_SOURCE_DIR",
    )
