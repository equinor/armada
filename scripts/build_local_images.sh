#!/usr/bin/env bash
#
# Build the service images from local working copies and point the integration
# tests at them, instead of the published :dev / :latest images.
#
# Why this exists
# ---------------
# The integration tests normally pull ghcr.io/equinor/{flotilla-backend,sara,
# isar-robot}. That means a change which spans armada *and* one of the services
# cannot be validated until the service change has been merged and an image
# published -- but the armada side of the change is what proves the service side
# works. This script closes that gap: build everything locally, run the suite,
# then merge in confidence.
#
# Usage
# -----
#   scripts/build_local_images.sh              # build and verify the images
#   scripts/build_local_images.sh --run        # ... and then run the full suite
#   scripts/build_local_images.sh --help
#
# Repository locations default to the superrepo sibling layout and can each be
# overridden:  ISAR_DIR  ISAR_ROBOT_DIR  FLOTILLA_DIR  SARA_DIR

set -euo pipefail

TAG="${LOCAL_IMAGE_TAG:-local}"
PLATFORM="linux/amd64"
RUN_TESTS=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARMADA_DIR="$(dirname "$SCRIPT_DIR")"
SIBLING_ROOT="$(dirname "$ARMADA_DIR")"

ISAR_DIR="${ISAR_DIR:-$SIBLING_ROOT/isar}"
ISAR_ROBOT_DIR="${ISAR_ROBOT_DIR:-$SIBLING_ROOT/isar-robot}"
FLOTILLA_DIR="${FLOTILLA_DIR:-$SIBLING_ROOT/flotilla}"
SARA_DIR="${SARA_DIR:-$SIBLING_ROOT/sara}"

FLOTILLA_IMAGE="flotilla-backend:$TAG"
SARA_IMAGE="sara:$TAG"
ISAR_ROBOT_IMAGE="isar-robot:$TAG"
ISAR_ROBOT_BASE_IMAGE="isar-robot:$TAG-base"

for arg in "$@"; do
    case "$arg" in
        --run) RUN_TESTS=true ;;
        --help|-h)
            # Print the header comment block, stopping at the first non-comment line.
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"
            exit 0 ;;
        *) echo "Unknown argument: $arg (try --help)" >&2; exit 2 ;;
    esac
done

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

require_dir() {
    [ -d "$1" ] || die "$2 not found at '$1'. Set $3 to override."
}

require_dir "$ISAR_DIR"        "isar repository"        ISAR_DIR
require_dir "$ISAR_ROBOT_DIR"  "isar-robot repository"  ISAR_ROBOT_DIR
require_dir "$FLOTILLA_DIR"    "flotilla repository"    FLOTILLA_DIR
require_dir "$SARA_DIR"        "sara repository"        SARA_DIR

docker info >/dev/null 2>&1 || die "Docker does not appear to be running."

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# flotilla-backend and sara are built straight from the working tree, so any
# uncommitted changes are included.
# ---------------------------------------------------------------------------

log "Building $FLOTILLA_IMAGE from $FLOTILLA_DIR"
docker build --platform "$PLATFORM" \
    -f "$FLOTILLA_DIR/backend/Dockerfile" \
    -t "$FLOTILLA_IMAGE" \
    "$FLOTILLA_DIR/backend"

log "Building $SARA_IMAGE from $SARA_DIR"
docker build --platform "$PLATFORM" -t "$SARA_IMAGE" "$SARA_DIR"

# ---------------------------------------------------------------------------
# isar-robot needs two steps.
#
# 1. Its Dockerfile does `RUN --mount=source=.git,target=.git,type=bind`, and
#    setuptools_scm needs that git directory both to derive a version *and* to
#    discover package data such as src/isar_robot/example_data/. In the superrepo
#    the checkout is a submodule, so `.git` is a FILE ("gitdir: ...") which the
#    `!.git/` allowlist entry in .dockerignore does not match. Building directly
#    from the working tree therefore fails with "unable to detect version", and
#    forcing SETUPTOOLS_SCM_PRETEND_VERSION instead produces a wheel that is
#    missing example_data -- which only shows up much later as
#    RobotRetrieveInspectionException during a mission. Cloning into a temporary
#    directory yields a real .git directory with history and tags, so the stock
#    Dockerfile works unmodified.
#
# 2. isar-robot's uv.lock pins `isar` from PyPI (the lock is generated with
#    --no-sources, so the `[tool.uv.sources] isar = { path = "../isar" }` entry in
#    pyproject.toml is ignored). To test local isar changes, the locally built
#    wheel is installed over the released one.
# ---------------------------------------------------------------------------

if [ -n "$(git -C "$ISAR_ROBOT_DIR" status --porcelain)" ]; then
    warn "$ISAR_ROBOT_DIR has uncommitted changes."
    warn "isar-robot is CLONED rather than built from the working tree, so those"
    warn "changes will NOT be in the image. Commit them first if they matter."
fi

log "Cloning isar-robot into a temporary directory (needs a real .git)"
git clone --quiet "$ISAR_ROBOT_DIR" "$TMP_DIR/isar-robot" \
    || die "Failed to clone $ISAR_ROBOT_DIR"

log "Building $ISAR_ROBOT_BASE_IMAGE"
docker build --platform "$PLATFORM" -t "$ISAR_ROBOT_BASE_IMAGE" "$TMP_DIR/isar-robot"

log "Building the isar wheel from $ISAR_DIR (working tree, uncommitted changes included)"
mkdir -p "$TMP_DIR/wheels"
if ! ( cd "$ISAR_DIR" && uv build --wheel -o "$TMP_DIR/wheels" ) >"$TMP_DIR/uv-build.log" 2>&1; then
    cat "$TMP_DIR/uv-build.log" >&2
    die "Failed to build the isar wheel"
fi
ISAR_WHEEL="$(ls "$TMP_DIR"/wheels/isar-*.whl 2>/dev/null | head -1)"
[ -n "$ISAR_WHEEL" ] || die "No isar wheel was produced in $TMP_DIR/wheels"
echo "Built $(basename "$ISAR_WHEEL")"

log "Overlaying the local isar onto $ISAR_ROBOT_IMAGE"
# The wheel keeps its original filename: uv rejects anything that is not a valid
# PEP 427 wheel name ("Must have a Python tag").
mkdir -p "$TMP_DIR/overlay/wheels"
cp "$ISAR_WHEEL" "$TMP_DIR/overlay/wheels/"
cat > "$TMP_DIR/overlay/Dockerfile" <<OVERLAY
FROM $ISAR_ROBOT_BASE_IMAGE
USER root
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY wheels /tmp/wheels
# --no-deps keeps the resolved dependency set from the base image. If isar ever
# gains a new dependency this will need revisiting.
RUN /bin/uv pip install --python /app/.venv/bin/python --no-deps --reinstall /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels
USER 1000
CMD ["isar-start"]
OVERLAY
docker build --platform "$PLATFORM" -t "$ISAR_ROBOT_IMAGE" "$TMP_DIR/overlay"

docker run --rm --platform "$PLATFORM" \
    --entrypoint /app/.venv/bin/python "$ISAR_ROBOT_IMAGE" -c '
import pathlib, sys
import isar_robot
from isar.config.settings import settings

problems = []

example_data = pathlib.Path(isar_robot.__file__).parent / "example_data"
count = len(list(example_data.iterdir())) if example_data.is_dir() else 0
if count == 0:
    problems.append(
        "isar_robot/example_data is missing or empty; the wheel was built without a "
        "usable git directory, and missions will fail with "
        "RobotRetrieveInspectionException"
    )

for problem in problems:
    print("  FAIL " + problem)
if problems:
    sys.exit(1)

print(f"  OK   isar-robot has {count} example_data files")
' || die "isar-robot image verification failed"

# ---------------------------------------------------------------------------

PYTEST_ENV=(
    "FLOTILLA_BACKEND_IMAGE=$FLOTILLA_IMAGE"
    "SARA_IMAGE=$SARA_IMAGE"
    "ISAR_ROBOT_IMAGE=$ISAR_ROBOT_IMAGE"
    # Take the database schema from the same checkouts the images were built
    # from, rather than cloning the app repositories from GitHub. Without this
    # you would run local application code against a remote schema, and any
    # migration that is unpushed or uncommitted would be missed entirely.
    "FLOTILLA_MIGRATIONS_SOURCE_DIR=$FLOTILLA_DIR"
    "SARA_MIGRATIONS_SOURCE_DIR=$SARA_DIR"
)

log "Images ready"
printf '  %s\n' "$FLOTILLA_IMAGE" "$SARA_IMAGE" "$ISAR_ROBOT_IMAGE"

if [ "$RUN_TESTS" = true ]; then
    log "Running the integration tests against the local images"
    cd "$ARMADA_DIR"
    env "${PYTEST_ENV[@]}" uv run --frozen pytest -n auto robotics_integration_tests
else
    log "Run the integration tests with:"
    echo
    printf '  cd %s\n' "$ARMADA_DIR"
    for pair in "${PYTEST_ENV[@]}"; do printf '  %s \\\n' "$pair"; done
    printf '  uv run --frozen pytest -n auto robotics_integration_tests\n\n'
    printf 'Or re-run this script with --run.\n\n'
fi
