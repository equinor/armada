import os
import re

from release_images import (
    copy_image,
    newest_stable_release,
    verify_release_tag,
    wait_for_commit_image,
)


def resolve_release_images(
    source_registry: str,
    destination_registry: str,
    image_names: list[str],
    version: str,
    commit: str,
    ghcr_image: str,
) -> dict[str, str]:
    digests = {}
    for name in image_names:
        reference = f"{source_registry}/{name}:dev.{commit[:8]}"
        digest = wait_for_commit_image(reference)
        verify_release_tag(f"{destination_registry}/{name}:{version}", digest)
        digests[name] = digest
    if ghcr_image:
        verify_release_tag(f"{ghcr_image}:{version}", digests[image_names[-1]])
    return digests


def publish_versioned_images(
    source_registry: str,
    destination_registry: str,
    digests: dict[str, str],
    version: str,
    ghcr_image: str,
    primary_image: str,
) -> None:
    for name, digest in digests.items():
        destination = f"{destination_registry}/{name}:{version}"
        if not verify_release_tag(destination, digest):
            copy_image(f"{source_registry}/{name}", destination, digest)
    if ghcr_image:
        digest = digests[primary_image]
        if not verify_release_tag(f"{ghcr_image}:{version}", digest):
            copy_image(
                f"{source_registry}/{primary_image}",
                f"{ghcr_image}:{version}",
                digest,
            )


def publish_latest_images(
    destination_registry: str,
    digests: dict[str, str],
    ghcr_image: str,
    primary_image: str,
) -> None:
    for name, digest in digests.items():
        image = f"{destination_registry}/{name}"
        copy_image(image, f"{image}:latest", digest)
    if ghcr_image:
        copy_image(
            f"{destination_registry}/{primary_image}",
            f"{ghcr_image}:latest",
            digests[primary_image],
        )


def publish_release() -> None:
    version = os.environ["VERSION"]
    commit = os.environ["SOURCE_COMMIT"]
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Expected vX.Y.Z release tag")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected the release source commit")
    source_registry = os.environ["SOURCE_REGISTRY"]
    destination_registry = os.environ["DESTINATION_REGISTRY"]
    primary_image = os.environ["IMAGE_NAME"]
    paired_image = os.environ.get("PAIRED_IMAGE_NAME", "")
    if paired_image == primary_image:
        raise ValueError("Paired image must differ from the primary image")
    image_names = [paired_image, primary_image] if paired_image else [primary_image]
    ghcr_image = ""
    if os.environ["PUSH_TO_GHCR"] == "true":
        owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
        ghcr_image = f"ghcr.io/{owner}/{primary_image.split('/')[-1]}"
    digests = resolve_release_images(
        source_registry, destination_registry, image_names, version, commit, ghcr_image
    )
    publish_versioned_images(
        source_registry,
        destination_registry,
        digests,
        version,
        ghcr_image,
        primary_image,
    )
    is_latest = version == newest_stable_release(os.environ["GITHUB_REPOSITORY"])
    if is_latest:
        publish_latest_images(destination_registry, digests, ghcr_image, primary_image)
    else:
        print(f"Published {version}; leaving latest and staging deployment unchanged")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"is_latest={str(is_latest).lower()}\n")
        output.write(f"digest={digests[primary_image]}\n")
        if paired_image:
            output.write(f"paired_digest={digests[paired_image]}\n")


if __name__ == "__main__":
    publish_release()
