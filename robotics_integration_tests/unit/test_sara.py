from unittest.mock import Mock

import pytest

from robotics_integration_tests.custom_containers.keycloak import Keycloak
from robotics_integration_tests.custom_containers.sara import create_sara_container
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.mqtt_credentials import MqttCredentials


@pytest.mark.parametrize("account", [settings.AZURITE_ACCOUNT, "customtestaccount"])
def test_all_storage_accounts_use_configured_azurite_account(monkeypatch, account):
    monkeypatch.setattr(settings, "AZURITE_ACCOUNT", account)
    connection_string = (
        f"AccountName={account};BlobEndpoint=http://sara-raw:10000/{account};"
    )
    container = create_sara_container(
        network=Mock(),
        keycloak=Keycloak(container=Mock(), port=8080, alias="keycloak"),
        database_connection_string="local-database",
        raw_storage_connection_string=connection_string,
        mqtt_credentials=MqttCredentials("", "", "", {"sara": "test-password"}),
    )

    assert container.env["Storage__RawStorageAccount"] == account
    assert container.env["Storage__AnonStorageAccount"] == account
    assert container.env["Storage__VisStorageAccount"] == account
    assert (
        container.env[f"BlobStorage__{account}__ConnectionString"] == connection_string
    )
    assert container.env["Authentication__Provider"] == "Oidc"
    assert container.env["KeyVault__UseKeyVault"] == "false"
    assert container.logging_thread is None
