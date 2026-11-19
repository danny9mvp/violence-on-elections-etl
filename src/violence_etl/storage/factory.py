"""Factory for selecting artifact storage services."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from violence_etl.storage.blob_storage import BlobArtifactStorage
from violence_etl.storage.local_storage import LocalArtifactStorage

if TYPE_CHECKING:
    from violence_etl.config.settings import Settings


class ArtifactStorageFactory:
    """Create artifact storage services for the configured environment."""

    @staticmethod
    def create(
        settings: "Settings",
        blob_service_client: Optional[Any] = None,
        credential: Optional[Any] = None,
        service_client: Optional[Any] = None,
        storage_client: Optional[Any] = None,
    ):
        if settings.is_sqlite:
            return LocalArtifactStorage(settings.bronze_dir)
        if settings.blob_storage is None:
            raise ValueError("blob storage configuration is required when ENV=PROD")
        injected_service = (
            service_client
            if service_client is not None
            else blob_service_client
        )
        return BlobArtifactStorage(
            settings.blob_storage,
            credential=credential,
            service_client=injected_service,
            storage_client=storage_client,
        )


def get_artifact_storage(
    settings: "Settings",
    blob_service_client: Optional[Any] = None,
    credential: Optional[Any] = None,
    service_client: Optional[Any] = None,
    storage_client: Optional[Any] = None,
):
    """Return the artifact storage service for ``settings``."""
    return ArtifactStorageFactory.create(
        settings,
        blob_service_client=blob_service_client,
        credential=credential,
        service_client=service_client,
        storage_client=storage_client,
    )
