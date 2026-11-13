import json
import re
import subprocess
import time


def inspect_digest(reference: str, allow_missing: bool = False) -> str | None:
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{json .Manifest}}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        missing = (
            "manifest unknown" in result.stderr.lower()
            or f"{reference}: not found" in result.stderr
        )
        if allow_missing and missing:
            return None
        raise RuntimeError(f"Cannot inspect {reference}: {result.stderr.strip()}")
    digest = json.loads(result.stdout)["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError(f"Invalid digest for {reference}: {digest}")
    return digest


def wait_for_commit_image(reference: str) -> str:
    for attempt in range(31):
        digest = inspect_digest(reference, allow_missing=True)
        if digest is not None:
            return digest
        if attempt < 30:
            print(f"Waiting for {reference} ({attempt + 1}/31)", flush=True)
            time.sleep(20)
    raise RuntimeError(f"Commit image {reference} was not published after 10 minutes")


def verify_release_tag(reference: str, digest: str) -> bool:
    existing = inspect_digest(reference, allow_missing=True)
    if existing is not None and existing != digest:
        raise RuntimeError(f"Refusing to move {reference} to a different digest")
    return existing is not None


def copy_image(source: str, destination: str, digest: str) -> None:
    subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--prefer-index=false",
            "--tag",
            destination,
            f"{source}@{digest}",
        ],
        check=True,
    )
    if inspect_digest(destination) != digest:
        raise RuntimeError(f"Copied digest differs for {destination}")
    print(f"Verified {destination} -> {digest}", flush=True)


def newest_stable_release(repository: str) -> str:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/releases?per_page=100",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    versions = {}
    for page in json.loads(result.stdout):
        for release in page:
            tag = release["tag_name"]
            if release["draft"] or release["prerelease"]:
                continue
            if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
                versions[tag] = tuple(int(part) for part in tag[1:].split("."))
    if not versions:
        raise RuntimeError("No stable versioned releases found")
    return max(versions, key=versions.__getitem__)
