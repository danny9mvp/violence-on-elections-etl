"""Blob-backed artifact storage service for PROD."""
from __future__ import annotations

import csv
import logging
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from violence_etl.clients.object_storage import ObjectStorageClient
from violence_etl.utils.io import SOURCE_STEM, sha256_bytes, utc_stamp

logger = logging.getLogger(__name__)

GOLD_TOP5 = "gold_top5_departments.csv"
GOLD_DEPT = "gold_crimes_by_department.csv"
GOLD_CAL = "gold_crimes_by_calendar.csv"
GOLD_PERIOD = "gold_crimes_by_electoral_period.csv"


class BlobArtifactStorage:
    """Persist bronze and gold CSV artifacts in object storage containers."""

    def __init__(
        self,
        blob_storage_config: Any,
        credential: Optional[Any] = None,
        storage_client: Optional[ObjectStorageClient] = None,
        service_client: Optional[Any] = None,
        blob_service_client: Optional[Any] = None,
    ) -> None:
        # TODO: Refactor constructor to only assign injected dependencies; move conditional creation and SDK import/credential logic to a factory or builder in a later feature.
        self.config = blob_storage_config
        if storage_client is not None:
            self._client = storage_client
        else:
            injected_service = (
                service_client
                if service_client is not None
                else blob_service_client
            )
            self._client = ObjectStorageClient(
                blob_storage_config.storage_account_name,
                credential=credential,
                service_client=injected_service,
            )

    @staticmethod
    def _landing_blob_name(sha: str) -> str:
        return "landing/{0}.csv".format(sha)

    @staticmethod
    def _raw_blob_name() -> str:
        return "raw/{0}_{1}.csv".format(SOURCE_STEM, utc_stamp())

    def landing_location(self, sha: str) -> str:
        return self._landing_blob_name(sha)

    def write_landing(self, data: bytes) -> Tuple[str, str, bool]:
        sha = sha256_bytes(data)
        blob_name = self._landing_blob_name(sha)
        if self._client.exists(self.config.bronze_container, blob_name):
            return blob_name, sha, False
        self._client.upload(self.config.bronze_container, blob_name, data, overwrite=False)
        return blob_name, sha, True

    def write_run_raw_copy(self, data: bytes) -> str:
        blob_name = self._raw_blob_name()
        self._client.upload(self.config.bronze_container, blob_name, data, overwrite=False)
        return blob_name

    def read_landing_csv(self, sha: str) -> pd.DataFrame:
        blob_name = self._landing_blob_name(sha)
        payload = self._client.download(self.config.bronze_container, blob_name)
        return pd.read_csv(
            BytesIO(payload),
            dtype=str,
            keep_default_na=False,
            quoting=csv.QUOTE_ALL,
        )

    def export_gold_csvs(
        self,
        export_dir: str,
        top5_records: List[Dict[str, object]],
        dept_records: List[Dict[str, object]],
        cal_records: List[Dict[str, object]],
        period_records: List[Dict[str, object]],
    ) -> None:
        files = [
            (GOLD_TOP5, pd.DataFrame(top5_records)),
            (GOLD_DEPT, pd.DataFrame(dept_records)),
            (GOLD_CAL, pd.DataFrame(cal_records)),
            (GOLD_PERIOD, pd.DataFrame(period_records)),
        ]
        for name, df in files:
            content = df.to_csv(index=False).encode("utf-8")
            self._client.upload(self.config.gold_container, name, content, overwrite=True)
        logger.info("gold: exported csv to container %s", self.config.gold_container)
