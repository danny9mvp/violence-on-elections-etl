"""Generic Azure Key Vault secret access."""
from __future__ import annotations

from typing import Any, Optional

_AZURE_IMPORT_ERROR = (
    "Azure Key Vault support requires 'azure-identity' and "
    "'azure-keyvault-secrets' to be installed"
)


class KeyVaultClient:
    """Read non-empty string secrets from an Azure Key Vault.

    Azure SDK imports happen only when no secret client is supplied. This keeps
    SQLite environments free of any Azure dependency and lets tests inject a
    fake client without installing or importing the SDK.
    """

    def __init__(
        self,
        vault_url: str,
        credential: Optional[Any] = None,
        secret_client: Optional[Any] = None,
    ) -> None:
        self.vault_url = vault_url
        self._secret_client = secret_client

        if secret_client is not None:
            return

        if credential is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:  # pragma: no cover - depends on installed extras
                raise ImportError(_AZURE_IMPORT_ERROR) from exc
            credential = DefaultAzureCredential()

        try:
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ImportError(_AZURE_IMPORT_ERROR) from exc

        self._secret_client = SecretClient(vault_url=vault_url, credential=credential)

    def get_secret(self, name: str) -> str:
        value = self._secret_client.get_secret(name).value
        if value is None or value == "":
            raise ValueError("Key Vault secret '{0}' is empty or missing".format(name))
        return value
