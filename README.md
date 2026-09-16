# armada
Repository for integration tests of the Equinor Flotilla robotics system. The term armada points to the integration tests deploying a large number of containers beyond the ones provided by Flotilla to perform full integration tests.

## Purpose
The integration tests shall replicate normal operation and error situations that can occur for a robot mission in Flotilla and determine whether the system handles the situation as expected. Whenever changes are made to the system, the integration tests will execute to verify that the behavior remains consistent.

The following components are currently included in the integration tests:

- [Flotilla Backend](https://github.com/equinor/flotilla/tree/main/backend) (C#)
- [Flotilla Broker](https://github.com/equinor/flotilla/tree/main/broker) (mosquitto mqtt broker)
- PostgreSQL database
- Azure Blob Storage (emulated with Azurite)
- [ISAR Robot](https://github.com/equinor/isar-robot) (your friendly neighbourhood mocked robot which provides the answers you need)
- [SARA](https://github.com/equinor/sara) (storage and analysis of robot acquired data)
- A local Keycloak realm (see [Authentication](#authentication))

## Authentication
The tests run with authentication **enabled and genuinely exercised**, but without Microsoft
Entra ID. A [Keycloak](https://www.keycloak.org/) container is the OpenID Connect issuer for the
whole stack: Flotilla and SARA run with `ASPNETCORE_ENVIRONMENT=IntegrationTest`, whose
`appsettings.IntegrationTest.json` sets `Authentication:Provider=Oidc`; ISAR is pointed at the
realm with `ISAR_OPENID_CONFIG_URL`; Flotilla acquires its downstream tokens from the realm too;
and the test process mints its own from the same issuer.

No app registrations, tenant or client secrets are needed. The fixtures assert that each service
rejects unauthenticated callers before any test runs, and the mission tests attempt unauthorised
interference mid-flight and then assert the mission completed unaffected.

MQTT needs no secret either. A CA, a broker certificate and a password per broker user are
generated per test run in `robotics_integration_tests/utilities/mqtt_credentials.py`; the broker
assembles them into its configuration on startup. They live only in memory and in the containers
of that run. TLS and the broker's ACLs are exercised exactly as in a deployed environment.

### The realm
`robotics_integration_tests/custom_realms/robotics-realm.json` is imported at startup. It is also
what a developer mounts to run flotilla or sara against Keycloak locally, so a local run and a CI
run exercise the same clients, scopes and roles.

Unlike Entra, Keycloak does not derive the audience from the requested scope: each API has a
client scope — `isar-api`, `sara-api`, `flotilla-api`, `pointilla-api` — carrying a single
audience mapper onto `isar-test`, `sara-test` and so on. **Request exactly one API scope per
token**; two audience mappers make Keycloak emit `aud` as an array, which ISAR rejects.

Keycloak has no ad-hoc token endpoint, so a role set is chosen by picking the service account
that holds it:

| Client | Roles |
| --- | --- |
| `integration-tests` | every role the three services require |
| `integration-tests-limited-role` | `Role.User.HUA` only — recognised, but insufficient |
| `integration-tests-no-role` | none |
| `flotilla-test` | used by Flotilla for its downstream ISAR/SARA calls |

Three protocol mappers exist only to satisfy `fastapi-azure-auth`'s Entra-shaped token model,
which ISAR uses: a hardcoded `ver`, a hardcoded `nbf` (Keycloak emits none, the library requires
it) and a flat `roles` claim, since the default nested `realm_access.roles` maps to neither
ISAR's `User.roles` nor .NET's `ClaimTypes.Role`.

## Run the integration tests through remote workflow call
To run the integration tests in a remote repository, this [workflow](./.github/workflows/run_integration_tests.yml) has been set up. 

In your repository, setup the following workflow:
```yaml
name: Run integration tests

# Chained off the deploy workflows rather than triggered directly by push or
# release. Both used to fire on the same event, so the tests started while the
# images were still building and pulled the previous :dev or :latest image.
#
# The names below must match the `name:` of deploy_to_development.yml and
# deploy_to_staging.yml. Renaming either one silently breaks this chain.
on:
  workflow_run:
    workflows: ["Deploy to Development", "Deploy to Staging"]
    types: [completed]
  workflow_dispatch:
    inputs:
      lane:
        description: "dev or latest"
        required: true
        default: latest

permissions:
  contents: read
  packages: read

concurrency:
  group: integration-tests-${{ github.event.workflow_run.name || inputs.lane }}
  cancel-in-progress: true

jobs:
  run-integration-tests:
    # A cancelled or failed deploy leaves the registry tag pointing at the
    # previous image, which is exactly what this workflow must not test.
    if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'
    uses: equinor/armada/.github/workflows/run_integration_tests.yml@main
    with:
      # Pick lane from the deploy workflow that triggered us, or honor manual input
      lane: ${{ github.event_name == 'workflow_run'
            && (github.event.workflow_run.name == 'Deploy to Development' && 'dev' || 'latest')
            || inputs.lane }}
```

This snippet will enable you to run the integration tests manually, and automatically once the
deploy workflow that publishes the images has finished. It needs no repository secrets: the
suite mints its own MQTT credentials per run, authenticates against a local Keycloak realm, and
pulls the service images from public ghcr.io packages.

SARA's container fixture explicitly sets every built-in analysis workflow's
`OutputStorageAccount` to `AZURITE_ACCOUNT`, using the same local blob connection as raw
storage. Output blob containers inherit the input installation container (such as `hua`),
which the storage fixture creates in Azurite. SARA's startup validation remains enabled;
new built-in workflows must also be configured in
`robotics_integration_tests/custom_containers/sara.py`.

The input `lane` determines the image tag used for the internally developed packages like
Flotilla and ISAR. `lane=dev` pulls `ghcr.io/equinor/<image>:dev`, the newest development images
corresponding to the newest push to main; `lane=latest` pulls `ghcr.io/equinor/<image>:latest`,
the newest release. These packages are public, so no registry credential is needed.

Both lanes read a mutable tag, so the tests must not start until the deploy workflow that
writes that tag has finished. Triggering on `push`/`release` directly makes the two run in
parallel and the tests then pull the *previous* image. This is why the snippet above chains off
`workflow_run` instead. There is no propagation delay to wait out beyond that: both registries
are single-region Basic ACRs with no geo-replication, and the registry API only acknowledges the
manifest `PUT` once the tag resolves to the new digest, so a successful deploy run means the tag
is already pullable.

Note that this orders the lane's tag for the repository that triggered the run only. The three
image producing repositories share the `:dev` and `:latest` tags, so a concurrent deploy in
another repository can still swap a different service's image mid-run.

## Shared .NET migration authentication

**Breaking change:** `run_dotnet_migrations.yml` requires Azure CLI authentication
with a dedicated migration identity for every deployed CI migration. There is no
legacy/password branch or authentication-mode input. Merging changes all callers
using `@main`: old releases and missing environment settings will fail closed.
Before merge/cutover, every affected environment needs its identity/federation,
database role/ownership/DDL permissions, variables, runner connectivity and a
supported application ref ready. This is not an independently safe prerequisite merge.

The selected GitHub Environment must define
`MIGRATION_CLIENT_ID`, `MIGRATION_POSTGRES_HOST`, `MIGRATION_POSTGRES_DATABASE` and
`MIGRATION_POSTGRES_USERNAME`, alongside the existing `AZURE_TENANT_ID` and
`AspNetEnvironment`. The existing `azure_subscription_id` input is also required.
The PostgreSQL username is the provisioned database role, not an inferred client ID
or identity display name. Provisioning, database ownership/DDL permissions and
runner connectivity must be established separately. No runtime `CLIENTID`, Key
Vault or GitHub credentials are deleted by this change.

Every run requires `.migration-auth-contract` in the checked-out `working_directory`,
containing exactly `azure-cli-postgresql-v1` followed by **one LF newline**.
Missing newline, CRLF, extra whitespace/newlines and unknown versions are rejected.
This reviewed source marker must ship atomically with factory support and tests;
it attests release capability, not runtime enforcement. Unsupported old releases
fail before Azure login, build or EF execution; there is no compatibility fallback.

The workflow logs in with `MIGRATION_CLIENT_ID`, then invokes EF without
`--verbose`, passing `Migrations__AuthenticationMode=AzureCli` and
`Migrations__Postgres__Host`, `Migrations__Postgres__Database`,
`Migrations__Postgres__Username`, plus `AZURE_TENANT_ID`. The supported factory must
use explicit `AzureCliCredential` for
`https://ossrdbms-aad.database.windows.net/.default`, manage token lifetime and TLS,
and fail on invalid configuration or authentication without reading Key Vault
passwords or falling back to runtime credential/auth-method arrays. The workflow
does not acquire or export database tokens.

Release callers must select the matching application `checkout_ref` (the default
remains `main`; `pr_head_sha` takes precedence) and gate deployment on successful
migrations. Temporary-database validation remains password-only and cloud-free.
Its EF steps and the disposable integration migration containers explicitly set
`Migrations__AuthenticationMode=LocalConnectionString` with
`ASPNETCORE_ENVIRONMENT=Development` and their direct
`Database__postgresConnectionString`. This local/test exception does not change
deployed CI authentication or remove local development/pgAdmin password access.
Local contract checks need only Python's standard library:

```bash
python3 -m unittest discover -s tests -p 'test_migration_workflow.py'
```

## Local development
Clone the repository and install dependencies with [uv](https://docs.astral.sh/uv/):
```bash
uv sync
```

The suite needs no secrets and no `.env`. Authentication runs against a local Keycloak realm and
the MQTT credentials are generated per run. The service images are public ghcr.io packages, so
no registry login is needed either.

You may now run the tests with

```bash
uv run pytest -s .
```

The fixture regression tests need no Docker daemon or image pulls:

```bash
uv run --frozen pytest robotics_integration_tests/unit
```

To run the dev lane, the same combination CI uses for a push to `main`:

```bash
export REGISTRY=ghcr.io/equinor
FLOTILLA_BACKEND_IMAGE=$REGISTRY/flotilla-backend:dev \
FLOTILLA_BROKER_IMAGE=$REGISTRY/flotilla-broker:dev \
ISAR_ROBOT_IMAGE=$REGISTRY/isar-robot:dev \
SARA_IMAGE=$REGISTRY/sara:dev \
GIT_REPOSITORY_FOR_MIGRATIONS_REF=dev \
SARA_GIT_REPOSITORY_FOR_MIGRATIONS_REF=dev \
uv run pytest -s -n auto robotics_integration_tests
```

### Running against locally built images

By default the tests pull `ghcr.io/equinor/{flotilla-backend,flotilla-broker,sara,isar-robot}`. A change that
spans armada *and* one of those services therefore cannot be verified until the service change
is merged and an image published — even though the armada side is what proves the service side
works.

To close that gap, build the images from your local working copies:

```bash
scripts/build_local_images.sh           # build and verify
scripts/build_local_images.sh --run     # ... and run the full suite against them
```

The script expects the sibling checkouts of the superrepo (`../isar`, `../isar-robot`,
`../flotilla`, `../sara`); override with `ISAR_DIR`, `ISAR_ROBOT_DIR`, `FLOTILLA_DIR`,
`SARA_DIR`. It verifies each image before handing back, because a subtly broken build otherwise
shows up only as an unexplained timeout several minutes into the suite.

The database schema is taken from the same local checkouts, via `FLOTILLA_MIGRATIONS_SOURCE_DIR`
and `SARA_MIGRATIONS_SOURCE_DIR`, so application code and schema always agree. The directory is
mounted read-only and copied into the migrations container, which means **uncommitted and
untracked migrations are picked up**. Set either variable on its own if you want to mix a local
schema with published images.

Two things worth knowing:

- **`flotilla`, `sara` and `isar` are built from the working tree**, so uncommitted changes are
  included. **`isar-robot` is cloned**, so only committed changes are — the script warns if that
  checkout is dirty. It has to be cloned because its Dockerfile bind-mounts `.git`, and in the
  superrepo that is a submodule *file* rather than a directory.
- `isar-robot`'s `uv.lock` pins `isar` from PyPI, so the locally built `isar` wheel is installed
  over the released one.

The mosquitto broker and Keycloak are always the published images.
