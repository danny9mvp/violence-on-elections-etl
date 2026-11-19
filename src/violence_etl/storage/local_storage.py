"""Local filesystem artifact storage for DEV/TEST."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Tuple

import pandas as pd

from violence_etl.utils.io import (
    SOURCE_STEM,
    landing_path,
    read_csv,
    sha256_bytes,
    utc_stamp,
)

logger = logging.getLogger(__name__)

GOLD_TOP5 = "gold_top5_departments.csv"
GOLD_DEPT = "gold_crimes_by_department.csv"
GOLD_CAL = "gold_crimes_by_calendar.csv"
GOLD_PERIOD = "gold_crimes_by_electoral_period.csv"


class LocalArtifactStorage:
    """Persist bronze and gold CSV artifacts on the local filesystem."""

    def __init__(self, bronze_dir: str) -> None:
        self.bronze_dir = bronze_dir

    def landing_location(self, sha: str) -> str:
        return landing_path(self.bronze_dir, sha)

    def write_landing(self, data: bytes) -> Tuple[str, str, bool]:
        """Write landing/<sha256>.csv if absent. Returns (path, sha, written)."""
        sha = sha256_bytes(data)
        path = self.landing_location(sha)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            return path, sha, False
        with open(path, "wb") as fh:
            fh.write(data)
        return path, sha, True

    def write_run_raw_copy(self, data: bytes) -> str:
        raw_dir = os.path.join(self.bronze_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        path = os.path.join(raw_dir, "{0}_{1}.csv".format(SOURCE_STEM, utc_stamp()))
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def read_landing_csv(self, sha: str) -> pd.DataFrame:
        return read_csv(self.landing_location(sha))

    def export_gold_csvs(
        self,
        export_dir: str,
        top5_records: List[Dict[str, object]],
        dept_records: List[Dict[str, object]],
        cal_records: List[Dict[str, object]],
        period_records: List[Dict[str, object]],
    ) -> None:
        os.makedirs(export_dir, exist_ok=True)
        pd.DataFrame(top5_records).to_csv(
            os.path.join(export_dir, GOLD_TOP5), index=False
        )
        pd.DataFrame(dept_records).to_csv(
            os.path.join(export_dir, GOLD_DEPT), index=False
        )
        pd.DataFrame(cal_records).to_csv(
            os.path.join(export_dir, GOLD_CAL), index=False
        )
        pd.DataFrame(period_records).to_csv(
            os.path.join(export_dir, GOLD_PERIOD), index=False
        )
        logger.info("gold: exported csv to %s", export_dir)
