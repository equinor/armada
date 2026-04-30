from typing import List, Union

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

    def delete_secret(self, secret_name: str) -> None:
        secret_client: SecretClient = self.get_secret_client()
        try:
            secret_client.begin_delete_secret(name=secret_name)
            logger.info(f"Secret {secret_name} was deleted from keyvault {self.name}")
        except ResourceNotFoundError:
            logger.warning(
                f"Secret {secret_name} not found in keyvault {self.name} during cleanup"
            )
        except HttpResponseError:
            logger.warning(
                f"Failed to delete secret {secret_name} from keyvault {self.name}",
                exc_info=True,
            )

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


class ScopedKeyvault(Keyvault):
    """A keyvault wrapper that namespaces all secret names with a unique prefix.

    This allows multiple test instances to use the same Azure Key Vault
    concurrently without overwriting each other's secrets. Secrets are
    automatically cleaned up when ``cleanup`` is called.
    """

    def __init__(
        self,
        prefix: str,
        keyvault_name: str,
        client_id: str = None,
        client_secret: str = None,
        tenant_id: str = None,
    ):
        super().__init__(
            keyvault_name=keyvault_name,
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
        )
        self.prefix = prefix
        self._created_secrets: List[str] = []

    def _scoped_name(self, secret_name: str) -> str:
        return f"{self.prefix}-{secret_name}"

    def get_secret(self, secret_name: str) -> KeyVaultSecret:
        return super().get_secret(self._scoped_name(secret_name))

    def set_secret(self, secret_name: str, secret_value) -> None:
        scoped = self._scoped_name(secret_name)
        super().set_secret(secret_name=scoped, secret_value=secret_value)
        self._created_secrets.append(scoped)

    def cleanup(self) -> None:
        """Delete all secrets created by this scoped instance."""
        for secret_name in self._created_secrets:
            self.delete_secret(secret_name)
        self._created_secrets.clear()
