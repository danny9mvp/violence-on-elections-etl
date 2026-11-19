"""Low-level object storage client for container and blob operations."""
from __future__ import annotations

from typing import Any, Optional

_STORAGE_IMPORT_ERROR = (
    "Object storage support requires 'azure-identity' and "
    "'azure-storage-blob' to be installed"
)


class ObjectStorageClient:
    """Access container objects through a lazy storage service client.

    Azure SDK imports happen only when no service client is supplied. This keeps
    SQLite environments free of storage SDK dependencies and lets tests inject a
    fake service client without installing or importing the SDK.
    """

    def __init__(
        self,
        storage_account_name: str,
        credential: Optional[Any] = None,
        service_client: Optional[Any] = None,
    ) -> None:
        # TODO: Refactor constructor to only assign injected dependencies; move conditional creation and SDK import/credential logic to a factory or builder in a later feature.
        self.storage_account_name = storage_account_name
        self._service_client = service_client

        if service_client is not None:
            return

        if credential is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:  # pragma: no cover - depends on installed extras
                raise ImportError(_STORAGE_IMPORT_ERROR) from exc
            credential = DefaultAzureCredential()

        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ImportError(_STORAGE_IMPORT_ERROR) from exc

        account_url = "https://{0}.blob.core.windows.net".format(storage_account_name)
        self._service_client = BlobServiceClient(
            account_url=account_url, credential=credential
        )

    def _blob_client(self, container_name: str, blob_name: str):
        container = self._service_client.get_container_client(container_name)
        return container.get_blob_client(blob_name)

    def exists(self, container_name: str, blob_name: str) -> bool:
        return self._blob_client(container_name, blob_name).exists()

    def upload(
        self,
        container_name: str,
        blob_name: str,
        data: bytes,
        overwrite: bool = False,
    ) -> None:
        self._blob_client(container_name, blob_name).upload_blob(
            data, overwrite=overwrite
        )

    def download(self, container_name: str, blob_name: str) -> bytes:
        return self._blob_client(container_name, blob_name).download_blob().readall()
