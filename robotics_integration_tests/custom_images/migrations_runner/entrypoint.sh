#!/usr/bin/env bash
set -euo pipefail

# ---------- Required inputs ----------
: "${DATABASE_URL:?DATABASE_URL must be set, e.g. postgresql://user:pwd@host:5432/mydb}"

# Optional inputs
GIT_REPO="${GIT_REPO:-equinor/flotilla}"
GIT_REF="${GIT_REF:-latest}"
EF_PROJECT_PATH="${EF_PROJECT_PATH:-backend/api}"
EF_STARTUP_PATH="${EF_STARTUP_PATH:-$EF_PROJECT_PATH}"
EF_CONTEXT="${EF_CONTEXT:-}"
WAIT_FOR_DB_TIMEOUT="${WAIT_FOR_DB_TIMEOUT:-60}"

rm -rf /work/repo
mkdir -p /work/repo

if [ -n "${LOCAL_REPO_PATH:-}" ]; then
  # Migrations come from a local checkout mounted read-only, so that locally
  # built service images and the database schema come from the same source.
  # Copied rather than used in place: the build writes bin/ and obj/ into the
  # project, and the mount is read-only precisely so the caller's working tree
  # cannot be modified.
  #
  # bin and obj are excluded not to save space but for correctness: they are
  # host-architecture build output, and obj/project.assets.json embeds absolute
  # host paths, both of which break restore inside this container.
  echo "Copying migrations source from $LOCAL_REPO_PATH ..."
  [ -d "$LOCAL_REPO_PATH" ] || { echo "LOCAL_REPO_PATH '$LOCAL_REPO_PATH' is not a directory."; exit 1; }
  tar -C "$LOCAL_REPO_PATH" \
      --exclude=bin \
      --exclude=obj \
      --exclude=node_modules \
      --exclude=.git \
      --exclude=TestResults \
      -cf - . | tar -C /work/repo -xf -
else
  echo "Cloning $GIT_REPO @ $GIT_REF ..."
  if [ "$GIT_REF" = "latest" ]; then
    BRANCH=$(curl -s ${GITHUB_TOKEN:+-H "Authorization: token $GITHUB_TOKEN"} \
      "https://api.github.com/repos/$GIT_REPO/releases/latest" | jq -r .tag_name)
    echo "Resolved latest to $BRANCH"
  else
    BRANCH="main"
  fi
  rm -rf /work/repo
  git clone --depth 1 --branch "$BRANCH" "https://github.com/$GIT_REPO" /work/repo
fi

cd /work/repo

# Guard against a source that does not contain what we expect, rather than
# letting it surface later as an opaque dotnet-ef failure.
if ! ls "$EF_PROJECT_PATH"/*.csproj >/dev/null 2>&1; then
  echo "No .csproj found at '$EF_PROJECT_PATH' in the migrations source."
  exit 1
fi

echo "Restoring projects for EF design-time..."
dotnet restore "$EF_STARTUP_PATH" || dotnet restore "$EF_PROJECT_PATH" || true

echo "Waiting for DB and applying migrations (timeout: ${WAIT_FOR_DB_TIMEOUT}s)..."
end=$((SECONDS + WAIT_FOR_DB_TIMEOUT))

# Loop until dotnet ef database update succeeds; when it does, migrations are applied
while true; do
  if dotnet ef database update \
      --connection "$DATABASE_URL" \
      --project "$EF_PROJECT_PATH" \
      --startup-project "$EF_STARTUP_PATH" ; then
    echo "Migrations applied successfully."
    break
  fi

  if (( SECONDS >= end )); then
    echo "Timed out waiting for DB (dotnet ef failed to connect)."
    exit 1
  fi
  sleep 1
done

echo "Migrations complete."
