#!/usr/bin/env bash
set -euo pipefail

# ---------- Required inputs ----------
: "${DATABASE_URL:?DATABASE_URL must be set, e.g. postgresql://user:pwd@host:5432/mydb}"

# Optional inputs
GIT_REPO="${GIT_REPO:-https://github.com/equinor/flotilla}"
GIT_REF="${GIT_REF:-main}"
EF_PROJECT_PATH="${EF_PROJECT_PATH:-backend/api}"
EF_STARTUP_PATH="${EF_STARTUP_PATH:-$EF_PROJECT_PATH}"
EF_CONTEXT="${EF_CONTEXT:-}"
WAIT_FOR_DB_TIMEOUT="${WAIT_FOR_DB_TIMEOUT:-60}"

# ---------- Secrets required by EF migrations to build ----------
: "${AZURE_CLIENT_SECRET:?AZURE_CLIENT_SECRET must be set at runtime}"
: "${AZURE_CLIENT_ID:?AZURE_CLIENT_ID must be set at runtime}"
: "${AZURE_TENANT_ID:?AZURE_TENANT_ID must be set at runtime}"

echo "Cloning $GIT_REPO @ $GIT_REF ..."
rm -rf /work/repo
git clone --depth 1 --branch "$GIT_REF" "$GIT_REPO" /work/repo

cd /work/repo

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
