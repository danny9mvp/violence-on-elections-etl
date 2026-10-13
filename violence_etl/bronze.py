"""Bronze layer: preserve the source verbatim and mirror it exactly.

No cleaning happens here. Every source field is stored as text together with
ingestion metadata (content hash, source file/url, load timestamp, row order).
"""
from __future__ import annotations

import datetime
import logging
import os
import time
from typing import Dict, Optional

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from violence_etl import io as etl_io
from violence_etl.models import BronzeCrimesRaw, BronzeIngestionLog
from violence_etl.schema import COLUMN_MAP, validate_header
from violence_etl.settings import Settings

logger = logging.getLogger(__name__)


def _naive_utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _already_loaded(engine: Engine, sha: str) -> bool:
    stmt = (
        select(BronzeIngestionLog.ingestion_id)
        .where(BronzeIngestionLog.source_sha256 == sha)
        .where(BronzeIngestionLog.status == "loaded")
        .limit(1)
    )
    with engine.connect() as conn:
        return conn.execute(stmt).first() is not None


def ingest_bronze(
    engine: Engine,
    settings: Settings,
    csv_path: Optional[str] = None,
    force: bool = False,
) -> Dict[str, object]:
    """Download (or read) the source CSV and load it into bronze_crimes_raw."""
    started = time.time()

    if csv_path is None:
        logger.info("bronze: downloading %s", settings.source_url)
        data = etl_io.download_source(settings.source_url)
        source_file = etl_io.write_run_raw_copy(settings.bronze_dir, data)
        landing, sha, written = etl_io.write_landing(settings.bronze_dir, data)
        logger.info("bronze: landing %s (new=%s) sha256=%s", landing, written, sha)
    else:
        if not os.path.exists(csv_path):
            raise FileNotFoundError(csv_path)
        with open(csv_path, "rb") as fh:
            data = fh.read()
        source_file = etl_io.write_run_raw_copy(settings.bronze_dir, data)
        landing, sha, written = etl_io.write_landing(settings.bronze_dir, data)
        logger.info("bronze: csv_path=%s sha256=%s", csv_path, sha)

    df = etl_io.read_csv(landing)
    validate_header(list(df.columns))

    if not force and _already_loaded(engine, sha):
        logger.info(
            "bronze: sha256=%s already loaded, skipping (use --force to reload)", sha
        )
        return {
            "status": "skipped",
            "source_sha256": sha,
            "source_file": source_file,
            "row_count": int(len(df)),
            "raw_rows": 0,
        }

    load_ts = _naive_utc_now()
    records = []
    for i, row in enumerate(df.to_dict("records"), start=1):
        rec = {
            "source_sha256": sha,
            "source_file": source_file,
            "source_url": settings.source_url,
            "load_ts": load_ts,
            "row_num": i,
        }
        for src_col, raw_col in COLUMN_MAP.items():
            value = row.get(src_col)
            rec[raw_col] = None if value is None else str(value)
        records.append(rec)

    with engine.begin() as conn:
        # Delete-then-insert for this sha keeps re-ingestion deterministic.
        conn.execute(
            delete(BronzeCrimesRaw).where(BronzeCrimesRaw.source_sha256 == sha)
        )
        if records:
            conn.execute(insert(BronzeCrimesRaw), records)
        conn.execute(
            insert(BronzeIngestionLog).values(
                source_url=settings.source_url,
                source_file=source_file,
                source_sha256=sha,
                row_count=len(records),
                status="loaded",
                message=None,
                loaded_at=load_ts,
            )
        )

    elapsed = time.time() - started
    logger.info(
        "bronze: loaded raw_rows=%d sha256=%s elapsed=%.2fs",
        len(records),
        sha,
        elapsed,
    )
    return {
        "status": "loaded",
        "source_sha256": sha,
        "source_file": source_file,
        "row_count": int(len(df)),
        "raw_rows": len(records),
        "elapsed_seconds": round(elapsed, 3),
    }


def latest_loaded_sha(engine: Engine) -> Optional[str]:
    """Return the sha256 of the most recent successful load, if any."""
    stmt = (
        select(BronzeIngestionLog.source_sha256)
        .where(BronzeIngestionLog.status == "loaded")
        .order_by(BronzeIngestionLog.loaded_at.desc(), BronzeIngestionLog.ingestion_id.desc())
        .limit(1)
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).first()
    return row[0] if row else None


def read_bronze_frame(engine: Engine, sha: str) -> pd.DataFrame:
    stmt = (
        select(
            BronzeCrimesRaw.row_num,
            BronzeCrimesRaw.fecha_hecho_raw,
            BronzeCrimesRaw.cod_depto_raw,
            BronzeCrimesRaw.departamento_raw,
            BronzeCrimesRaw.cod_muni_raw,
            BronzeCrimesRaw.municipio_raw,
            BronzeCrimesRaw.zona_raw,
            BronzeCrimesRaw.cantidad_raw,
        )
        .where(BronzeCrimesRaw.source_sha256 == sha)
        .order_by(BronzeCrimesRaw.row_num)
    )
    return pd.read_sql(stmt, engine)
