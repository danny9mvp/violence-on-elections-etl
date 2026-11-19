"""Pipeline orchestration: bronze then silver then gold."""
from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy.engine import Engine

from violence_etl.config.settings import Settings
from violence_etl.transformations.bronze import ingest_bronze
from violence_etl.transformations.gold import build_gold
from violence_etl.transformations.silver import build_silver

logger = logging.getLogger(__name__)


def run_bronze(
    engine: Engine,
    settings: Settings,
    csv_path: Optional[str] = None,
    force: bool = False,
) -> Dict[str, object]:
    return ingest_bronze(engine, settings, csv_path=csv_path, force=force)


def run_silver(
    engine: Engine,
    settings: Settings,
    sha: Optional[str] = None,
    force: bool = False,
) -> Dict[str, object]:
    return build_silver(engine, settings, sha=sha, force=force)


def run_gold(
    engine: Engine,
    export_csv: bool = False,
    export_dir: str = "data/gold",
    settings: Optional[Settings] = None,
) -> Dict[str, object]:
    return build_gold(engine, export_csv=export_csv, export_dir=export_dir, settings=settings)


def run_all(
    engine: Engine,
    settings: Settings,
    csv_path: Optional[str] = None,
    force: bool = False,
    export_csv: bool = False,
) -> Dict[str, Dict[str, object]]:
    logger.info("pipeline: run-all start (env=%s)", settings.env)
    bronze = run_bronze(engine, settings, csv_path=csv_path, force=force)
    silver = run_silver(engine, settings, sha=str(bronze.get("source_sha256") or "") or None, force=force)
    gold = run_gold(engine, export_csv=export_csv, settings=settings)
    logger.info(
        "pipeline: run-all done raw=%s silver=%s total_crimes=%s",
        bronze.get("raw_rows"),
        silver.get("silver_rows"),
        silver.get("total_crimes"),
    )
    return {"bronze": bronze, "silver": silver, "gold": gold}
