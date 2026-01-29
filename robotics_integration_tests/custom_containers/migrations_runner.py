from pathlib import Path

from docker.models.networks import Network
from testcontainers.core.image import DockerImage

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings


def create_migrations_runner_container(
    network: Network, postgres_connection_string: str
) -> StreamLoggingDockerContainer:
    migrations_runner_image: DockerImage = DockerImage(
        path=str(Path(settings.RELATIVE_PATH_TO_DOCKERFILE).resolve(strict=True)),
        tag="flotilla-migrations-runner",
    ).build()

    container = (
        StreamLoggingDockerContainer(image=str(migrations_runner_image))
        .with_name("migrations_runner")
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
    return container
