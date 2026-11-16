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
from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from violence_etl.utils import io as etl_io
from violence_etl.db.models.bronze_crimes_raw import BronzeCrimesRaw
from violence_etl.db.models.bronze_ingestion_log import BronzeIngestionLog
from violence_etl.utils.schema import COLUMN_MAP, validate_header
from violence_etl.config.settings import Settings
from violence_etl.utils.timeutil import naive_utc_now

logger = logging.getLogger(__name__)


def _has_raw_rows(engine: Engine, sha: str) -> bool:
    """True when a snapshot for ``sha`` is already present in bronze.

    Presence of the data, not the log status, is what makes a re-ingest a
    no-op: the log row for a hash is updated in place, so its status reflects
    only the most recent attempt.
    """
    stmt = (
        select(BronzeCrimesRaw.raw_id)
        .where(BronzeCrimesRaw.source_sha256 == sha)
        .limit(1)
    )
    with engine.connect() as conn:
        return conn.execute(stmt).first() is not None


def _upsert_ingestion_log(
    conn,
    *,
    source_url: str,
    source_file: str,
    source_sha256: str,
    row_count: int,
    status: str,
    message: Optional[str],
    loaded_at: datetime.datetime,
) -> None:
    """Insert or update the single log row for ``source_sha256``."""
    values = {
        "source_url": source_url,
        "source_file": source_file,
        "source_sha256": source_sha256,
        "row_count": row_count,
        "status": status,
        "message": message,
        "loaded_at": loaded_at,
    }
    update_cols = {k: v for k, v in values.items() if k != "source_sha256"}
    dialect = conn.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:  # pragma: no cover - only sqlite/postgres are supported
        dialect_insert = None

    if dialect_insert is not None:
        stmt = dialect_insert(BronzeIngestionLog).values(**values)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["source_sha256"], set_=update_cols
            )
        )
    else:  # pragma: no cover
        conn.execute(
            delete(BronzeIngestionLog).where(
                BronzeIngestionLog.source_sha256 == source_sha256
            )
        )
        conn.execute(insert(BronzeIngestionLog).values(**values))


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

    if not force and _has_raw_rows(engine, sha):
        skip_ts = naive_utc_now()
        with engine.begin() as conn:
            _upsert_ingestion_log(
                conn,
                source_url=settings.source_url,
                source_file=source_file,
                source_sha256=sha,
                row_count=int(len(df)),
                status="skipped",
                message="already loaded; use --force to reload",
                loaded_at=skip_ts,
            )
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

    load_ts = naive_utc_now()
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
        _upsert_ingestion_log(
            conn,
            source_url=settings.source_url,
            source_file=source_file,
            source_sha256=sha,
            row_count=len(records),
            status="loaded",
            message=None,
            loaded_at=load_ts,
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
    """Return the sha256 of the most recently loaded snapshot.

    Derived from the raw rows themselves (highest ``raw_id``) rather than the
    ingestion log, whose status reflects the latest attempt and may be
    ``skipped``.
    """
    stmt = (
        select(BronzeCrimesRaw.source_sha256)
        .group_by(BronzeCrimesRaw.source_sha256)
        .order_by(func.max(BronzeCrimesRaw.raw_id).desc())
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
