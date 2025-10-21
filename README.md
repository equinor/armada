# armada
Repository for integration tests of the Equinor Flotilla robotics system. The term armada points to the integration tests deploying a large number of containers beyond the ones provided by Flotilla to perform full integration tests.

## Purpose
The integration tests shall replicate normal operation and error situations that can occurr for a robot mission in Flotilla and determine whether the system handles the situation as expected. Whenever changes are made to the system, the integration tests will execute to verify that the bahvior remains consistent.

The following components are currently included in the integration tests:

- [Flotilla Backend](https://github.com/equinor/flotilla/tree/main/backend) (C#)
- [Flotilla Broker](https://github.com/equinor/flotilla/tree/main/broker) (mosquitto mqtt broker)
- PostgreSQL database
- Azure Blob Storage (emulated with Azurite)
- [ISAR Robot](https://github.com/equinor/isar-robot) (your friendly neighbourhood mocked robot which provides the answers you need)

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

The input `lane` determines which image tag should be applied to the internally developed packages like Flotilla and ISAR. If input is set as `lane=dev` the newest development images (corresponding to newest push to main branch) will be used while `lane=latest` will use the newest release. 

## Local development
Clone the repository and install the packages in your virtual environment.
```bash
pip install robotics_integration_tests/requirements.txt
```

Ensure the following secrets are populated in your local environment, either as environment variables or in a .env file in the repository root directory. 

```
INTEGRATION_TESTS_CLIENT_SECRET
FLOTILLA_AZURE_CLIENT_SECRET
FLOTILLA_BROKER_SERVER_KEY
FLOTILLA_MQTT_PASSWORD
ISAR_AZURE_CLIENT_SECRET
ISAR_MQTT_PASSWORD
```

They may all be found in the integration test [keyvualt](https://portal.azure.com/#@StatoilSRM.onmicrosoft.com/resource/subscriptions/c389567b-2dd0-41fa-a5da-d86b81f80bda/resourceGroups/FlotillaIntegrationTests/providers/Microsoft.KeyVault/vaults/FlotillaTestsKv/overview).

You may now run the tests with

```bash
pytest -s -n 10 .
```