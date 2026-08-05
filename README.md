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
- A local OAuth2 mock issuer (see [Authentication](#authentication))

## Authentication
The tests run with authentication **enabled and genuinely exercised**, but without Microsoft
Entra ID. A local [oauth2-mock-server](https://github.com/axa-group/oauth2-mock-server)
container acts as the OpenID Connect issuer for the whole stack:

- Flotilla and SARA run with `ASPNETCORE_ENVIRONMENT=IntegrationTest`, which selects their
  `appsettings.IntegrationTest.json` and points token validation at the mock.
- ISAR is pointed at the mock with `ISAR_OPENID_CONFIG_URL`.
- Flotilla acquires its downstream ISAR/SARA tokens from the mock too, via a
  `GenericOidcAuthorizationHeaderProvider` registered only in that environment.
- The test process mints its own tokens from the same issuer.

This means **no app registrations, no tenant and no client secrets** are needed, and there is
nothing to rotate. The container fixtures assert that each service rejects unauthenticated
callers before any test runs, and the mission tests attempt unauthorised interference mid-flight
(wrong audience, missing role) and then assert the mission completed unaffected — so a
misconfiguration cannot silently disable authentication.

MQTT is the one exception: it uses username/password validated by the broker against the
hashed `passwd_file` committed in `equinor/flotilla`, so those credentials remain real secrets.

## Run the integration tests through remote workflow call
To run the integration tests in a remote repository, this [workflow](./.github/workflows/run_integration_tests.yml) has been set up. 

In your repository, setup the following workflow:
```yaml
name: Run integration tests

on:
  push:
    branches: [ main ]
  release:
    types: [ published ]
  workflow_dispatch:
    inputs:
      lane:
        description: "dev or latest"
        required: true
        default: latest

permissions:
  contents: read
  packages: read

jobs:
  run-integration-tests:
    uses: equinor/armada/.github/workflows/run_integration_tests.yml@main
    with:
      # Pick lane automatically based on event, or honor manual input
      lane: ${{ github.event_name == 'push' && 'dev'
            || github.event_name == 'release' && 'latest'
            || github.event_name == 'workflow_dispatch' && inputs.lane
            || 'latest' }}

    secrets:
      INTEGRATION_TEST_AZURE_CLIENT_SECRET: ${{ secrets.INTEGRATION_TEST_AZURE_CLIENT_SECRET }}
```

This snippet will enable you to run the integration tests manually and automatically on push to main and published release. It requires the following secret to be set in your repository secrets:

```
INTEGRATION_TEST_AZURE_CLIENT_SECRET
```

This secret now only grants read access to the MQTT credentials in the key vault; it is no
longer used for authentication between the services. It is still declared by every consuming
repository, so it is kept for compatibility rather than removed.

The input `lane` determines which image tag should be applied to the internally developed packages like Flotilla and ISAR. If input is set as `lane=dev` the newest development images (corresponding to newest push to main branch) will be used while `lane=latest` will use the newest release. 

## Local development
Clone the repository and install dependencies with [uv](https://docs.astral.sh/uv/):
```bash
uv sync
```

Ensure the following secrets are populated in your local environment, either as environment variables or in a `.env` file in the repository root directory. These are the MQTT credentials; no
Azure app registration secrets are needed, and you do **not** need to be logged in with `az`.

```
FLOTILLA_BROKER_SERVER_KEY
FLOTILLA_MQTT_PASSWORD
ISAR_MQTT_PASSWORD
SARA_MQTT_PASSWORD
```

They may be found in the integration test [keyvault](https://portal.azure.com/#@StatoilSRM.onmicrosoft.com/resource/subscriptions/c389567b-2dd0-41fa-a5da-d86b81f80bda/resourceGroups/FlotillaIntegrationTests/providers/Microsoft.KeyVault/vaults/FlotillaTestsKv/overview).

You may now run the tests with

```bash
uv run pytest -s .
```

### Running against locally built images

By default the tests pull `ghcr.io/equinor/{flotilla-backend,sara,isar-robot}`. A change that
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

The mosquitto broker is always the published image, and the OAuth2 mock is built automatically
by the test fixtures.
