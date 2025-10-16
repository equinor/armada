from typing import Union

from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.keyvault.secrets import KeyVaultSecret, SecretClient
from loguru import logger


class Keyvault:
    def __init__(
        self,
        keyvault_name: str,
        client_id: str = None,
        client_secret: str = None,
        tenant_id: str = None,
    ):
        self.name = keyvault_name
        self.url = "https://" + keyvault_name + ".vault.azure.net"
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.client: SecretClient = None

    def get_secret(self, secret_name: str) -> KeyVaultSecret:
        secret_client: SecretClient = self.get_secret_client()
        try:
            secret: KeyVaultSecret = secret_client.get_secret(name=secret_name)
        except ResourceNotFoundError:
            logger.exception(
                f"Secret {secret_name} was not found in keyvault {self.name}"
            )
            raise
        except HttpResponseError:
            logger.error(
                "An error occurred while retrieving the secret '%s' from keyvault '%s'.",
                secret_name,
                self.name,
                exc_info=True,
            )
            raise

        return secret

    def set_secret(self, secret_name: str, secret_value) -> None:
        secret_client: SecretClient = self.get_secret_client()
        try:
            secret_client.set_secret(name=secret_name, value=secret_value)
            logger.info(f"Secret {secret_name} was set in keyvault {self.name}")
        except HttpResponseError:
            logger.exception(
                f"An error occurred while setting secret {secret_name} in keyvault {self.name}"
            )
            raise

    def get_secret_client(self) -> SecretClient:
        if self.client is None:
            try:
                credential: Union[ClientSecretCredential, DefaultAzureCredential]
                if self.client_id and self.client_secret and self.tenant_id:
                    credential = ClientSecretCredential(
                        tenant_id=self.tenant_id,
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                    )
                else:
                    credential = DefaultAzureCredential()
            except ClientAuthenticationError:
                logger.error(
                    "Failed to authenticate to Azure while connecting to KeyVault",
                    exc_info=True,
                )
                raise

            self.client = SecretClient(vault_url=self.url, credential=credential)
        return self.client
