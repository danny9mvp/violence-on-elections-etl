"""Silver layer: typed, cleaned, deduplicated, validated, calendar-enriched.

Cleaning rules R1..R13 are documented in docs/PLAN.md. The rule order is kept
literal: R1 strip, R2 upper, R3 codes, R4 date, R5 cantidad, R6 zona, R7 null,
R8 referential sanity, R9 dedup, R11..R13 enrichment.

Type rules (R3/R4/R5/R6) only flag *non-empty* invalid values. An empty cell is
left for R7 so it is reported as ``null_field`` rather than as a type error.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

from violence_etl.config.settings import Settings
from violence_etl.db.models.silver_crimes import SilverCrimes
from violence_etl.db.models.silver_rejected_rows import SilverRejectedRows
from violence_etl.exceptions.load_exception import LoadException
from violence_etl.transformations.bronze import latest_loaded_sha, read_bronze_frame
from violence_etl.utils.periods import electoral_period
from violence_etl.utils.timeutil import naive_utc_now

logger = logging.getLogger(__name__)

BUSINESS_KEY = ["fecha_hecho", "cod_depto", "cod_muni", "zona", "cantidad"]
DEDUP_KEY = ["fecha_hecho", "cod_depto", "cod_muni", "zona"]

ALLOWED_ZONA = ("URBANA", "RURAL")
VALID_DATE_FORMAT = "%d/%m/%Y"
NULLABLE_CHECK_COLUMNS = [
    "fecha_hecho",
    "cod_depto",
    "departamento",
    "cod_muni",
    "municipio",
    "zona",
    "cantidad",
]


def _is_empty(series: pd.Series) -> pd.Series:
    """True where the (already stripped) value is None or an empty string."""
    return series.isna() | (series.astype(str).str.strip() == "")


def _assign_reason(
    frame: pd.DataFrame, open_mask: pd.Series, fail_mask: pd.Series, reason: str
) -> pd.Series:
    """Set ``reject_reason`` on rows that fail, then narrow the open mask."""
    newly = open_mask & fail_mask
    frame.loc[newly, "reject_reason"] = reason
    return open_mask & ~newly


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply rules R1..R8 in place and return the frame with reject_reason."""
    df = frame.copy()
    df["reject_reason"] = None

    # R1: strip every text field.
    for col in [
        "fecha_hecho_raw",
        "cod_depto_raw",
        "departamento_raw",
        "cod_muni_raw",
        "municipio_raw",
        "zona_raw",
        "cantidad_raw",
    ]:
        df[col] = df[col].astype(str).str.strip()

    # Rename raw -> curated names for the working frame.
    df["fecha_raw"] = df["fecha_hecho_raw"]
    df["cod_depto"] = df["cod_depto_raw"]
    df["departamento"] = df["departamento_raw"]
    df["cod_muni"] = df["cod_muni_raw"]
    df["municipio"] = df["municipio_raw"]
    df["zona"] = df["zona_raw"]
    df["cantidad_raw_s"] = df["cantidad_raw"]

    # R2: uppercase descriptive text.
    for col in ["departamento", "municipio", "zona"]:
        df[col] = df[col].str.upper()

    open_mask = pd.Series(True, index=df.index)

    # R3: codes must be numeric and fit the fixed widths; pad with zeros.
    # Empty cells are left for R7 so they are reported as null_field, matching
    # the type rules: only non-empty invalid values are code exceptions.
    depto_empty = _is_empty(df["cod_depto"])
    depto_valid = df["cod_depto"].str.fullmatch(r"\d{1,2}").fillna(False)
    open_mask = _assign_reason(
        df, open_mask, ~depto_valid & ~depto_empty, "bad_cod_depto"
    )
    depto_ok = open_mask & depto_valid
    df.loc[depto_ok, "cod_depto"] = df.loc[depto_ok, "cod_depto"].str.zfill(2)

    muni_empty = _is_empty(df["cod_muni"])
    muni_valid = df["cod_muni"].str.fullmatch(r"\d{1,5}").fillna(False)
    open_mask = _assign_reason(
        df, open_mask, ~muni_valid & ~muni_empty, "bad_cod_muni"
    )
    muni_ok = open_mask & muni_valid
    df.loc[muni_ok, "cod_muni"] = df.loc[muni_ok, "cod_muni"].str.zfill(5)

    # R4: explicit DD/MM/YYYY parsing; never let pandas infer.
    parsed = pd.to_datetime(df["fecha_raw"], format=VALID_DATE_FORMAT, errors="coerce")
    df["fecha_hecho"] = parsed
    date_empty = _is_empty(df["fecha_raw"])
    open_mask = _assign_reason(
        df, open_mask, (parsed.isna() & ~date_empty), "bad_date"
    )

    # R5: cantidad to integer; non numeric, negative or fractional is invalid.
    numeric = pd.to_numeric(df["cantidad_raw_s"], errors="coerce")
    df["cantidad"] = numeric
    cantidad_empty = _is_empty(df["cantidad_raw_s"])
    non_integral = numeric.notna() & ((numeric % 1) != 0)
    bad_cantidad = (numeric.isna() | (numeric < 0) | non_integral) & ~cantidad_empty
    open_mask = _assign_reason(df, open_mask, bad_cantidad, "bad_cantidad")

    # R6: zona must be URBANA or RURAL.
    zona_empty = _is_empty(df["zona"])
    bad_zona = ~df["zona"].isin(ALLOWED_ZONA) & ~zona_empty
    open_mask = _assign_reason(df, open_mask, bad_zona, "bad_zona")

    # R7: null/empty check on the business columns.
    null_mask = pd.Series(False, index=df.index)
    for col in NULLABLE_CHECK_COLUMNS:
        if col == "fecha_hecho":
            null_mask = null_mask | df["fecha_hecho"].isna() & date_empty
        elif col == "cantidad":
            null_mask = null_mask | (cantidad_empty)
        elif col == "zona":
            null_mask = null_mask | zona_empty
        else:
            null_mask = null_mask | _is_empty(df[col])
    open_mask = _assign_reason(df, open_mask, null_mask, "null_field")

    # R8: cod_depto must be the first two chars of cod_muni.
    mismatch = df["cod_depto"].astype(str) != df["cod_muni"].astype(str).str[:2]
    open_mask = _assign_reason(df, open_mask, mismatch, "depto_muni_mismatch")

    return df

def _valid_with_sum_quantity(valid: pd.DataFrame) -> pd.DataFrame:
    group_key = ["fecha_hecho", "cod_depto", "departamento", "cod_muni", "municipio", "zona"]
    return valid.groupby(group_key).agg({
        "cantidad": "sum",
    }).reset_index()


def _dedup(valid: pd.DataFrame, mode: str) -> pd.DataFrame:
    """R9: collapse exact duplicate business rows."""
    if valid.empty:
        return valid
    if mode == "sum":
        agg = {c: "first" for c in valid.columns if c not in DEDUP_KEY + ["cantidad"]}
        agg["cantidad"] = "sum"
        grouped = valid.groupby(DEDUP_KEY, as_index=False).agg(agg)
        return grouped
    return valid.drop_duplicates(subset=BUSINESS_KEY, keep="first")


def _row_hash(fecha, cod_depto, cod_muni, zona, cantidad) -> str:
    canonical = "{0}|{1}|{2}|{3}|{4}".format(
        fecha, cod_depto, cod_muni, zona, int(cantidad)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _enrich(valid: pd.DataFrame, sha: str) -> pd.DataFrame:
    """R11..R13: calendar columns, electoral period, row hash, load timestamp."""
    df = valid.copy()
    dt = pd.to_datetime(df["fecha_hecho"])
    df["fecha_hecho"] = dt.dt.date
    df["year"] = dt.dt.year.astype(int)
    df["month"] = dt.dt.month.astype(int)
    df["quarter"] = ((df["month"] - 1) // 3 + 1).astype(int)
    df["weekday_num"] = (dt.dt.weekday + 1).astype(int)
    df["weekday_name"] = dt.dt.day_name()
    df["electoral_period"] = df["year"].map(electoral_period)
    df["cantidad"] = df["cantidad"].astype(int)
    df["row_hash"] = [
        _row_hash(f, d, m, z, c)
        for f, d, m, z, c in zip(
            df["fecha_hecho"],
            df["cod_depto"],
            df["cod_muni"],
            df["zona"],
            df["cantidad"],
        )
    ]
    df["source_sha256"] = sha
    df["silver_loaded_at"] = naive_utc_now()
    return df


def _silver_records(df: pd.DataFrame) -> List[Dict[str, object]]:
    cols = [
        "fecha_hecho",
        "cod_depto",
        "departamento",
        "cod_muni",
        "municipio",
        "zona",
        "cantidad",
        "year",
        "month",
        "quarter",
        "weekday_num",
        "weekday_name",
        "electoral_period",
        "row_hash",
        "source_sha256",
        "silver_loaded_at",
    ]
    return df[cols].to_dict("records")


def _insert_ignore(conn, model, records) -> int:
    """Insert ``records``, ignoring business-key conflicts. Return rowcount.

    The returned count is the number of rows actually written this run, which
    differs from ``len(records)`` when a re-run hits existing rows.
    """
    if not records:
        return 0
    dialect = conn.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:  # pragma: no cover - only sqlite/postgres are supported
        dialect_insert = None

    if dialect_insert is not None:
        stmt = dialect_insert(model).on_conflict_do_nothing()
    else:  # pragma: no cover
        stmt = model.__table__.insert()
    result = conn.execute(stmt, records)
    return int(result.rowcount if result.rowcount is not None else 0)


def build_silver(
    engine: Engine,
    settings: Settings,
    sha: Optional[str] = None,
    force: bool = False,
) -> Dict[str, object]:
    """Curate bronze rows into silver_crimes and silver_rejected_rows."""
    started = time.time()
    sha = sha or latest_loaded_sha(engine)
    if not sha:
        raise LoadException("No bronze data found. Run ingest-bronze first.")

    raw = read_bronze_frame(engine, sha)
    raw_rows = int(len(raw))

    cleaned = _clean(raw)
    reject_mask = cleaned["reject_reason"].notna()
    rejected = cleaned[reject_mask]
    valid = cleaned[~reject_mask]

    valid_before = int(len(valid))

    with_sum_quantity = _valid_with_sum_quantity(valid)
    deduped = _dedup(with_sum_quantity, settings.dedup_mode)
    dropped = valid_before - int(len(deduped))

    enriched = _enrich(deduped, sha)
    silver_records = _silver_records(enriched)

    loaded_at = naive_utc_now()
    rejected_records = []
    for rec in rejected.to_dict("records"):
        raw_values = {
            "FECHA HECHO": rec.get("fecha_hecho_raw"),
            "COD_DEPTO": rec.get("cod_depto_raw"),
            "DEPARTAMENTO": rec.get("departamento_raw"),
            "COD_MUNI": rec.get("cod_muni_raw"),
            "MUNICIPIO": rec.get("municipio_raw"),
            "ZONA": rec.get("zona_raw"),
            "CANTIDAD": rec.get("cantidad_raw"),
        }
        rejected_records.append(
            {
                "source_sha256": sha,
                "row_num": int(rec["row_num"]),
                "reject_reason": rec["reject_reason"],
                "raw_values": json.dumps(raw_values, ensure_ascii=False),
                "rejected_at": loaded_at,
            }
        )

    # Silver holds exactly one active snapshot: the target sha. Rows from any
    # previous export are purged so uniqueness on the business key is global
    # and gold (which reads all of silver) never mixes snapshots.
    with engine.begin() as conn:
        conn.execute(
            delete(SilverCrimes).where(SilverCrimes.source_sha256 != sha)
        )
        conn.execute(
            delete(SilverRejectedRows).where(SilverRejectedRows.source_sha256 != sha)
        )
        if force:
            conn.execute(
                delete(SilverCrimes).where(SilverCrimes.source_sha256 == sha)
            )
        inserted_rows = _insert_ignore(conn, SilverCrimes, silver_records)

        # Rejected rows are rebuilt per sha so repeated runs stay idempotent.
        conn.execute(
            delete(SilverRejectedRows).where(SilverRejectedRows.source_sha256 == sha)
        )
        if rejected_records:
            rejected_result = conn.execute(
                SilverRejectedRows.__table__.insert(), rejected_records
            )
            rejected_rows = int(
                rejected_result.rowcount if rejected_result.rowcount is not None else 0
            )
        else:
            rejected_rows = 0

        # Report what is in the database for the active snapshot, not the
        # in-memory frame (they agree, but the DB is the source of truth).
        db_silver_rows = int(
            conn.execute(select(func.count()).select_from(SilverCrimes)).scalar() or 0
        )
        db_total_crimes = int(
            conn.execute(
                select(func.coalesce(func.sum(SilverCrimes.cantidad), 0))
            ).scalar()
            or 0
        )

    result = {
        "source_sha256": sha,
        "raw_rows": raw_rows,
        "silver_rows": db_silver_rows,
        "inserted_rows": inserted_rows,
        "rejected_rows": rejected_rows,
        "dropped_duplicates": dropped,
        "total_crimes": db_total_crimes,
        "dedup_mode": settings.dedup_mode,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    logger.info(
        "silver: raw_rows=%d silver_rows=%d inserted=%d rejected=%d "
        "dropped_duplicates=%d total_crimes=%d mode=%s sha256=%s elapsed=%.2fs",
        raw_rows,
        result["silver_rows"],
        inserted_rows,
        rejected_rows,
        dropped,
        db_total_crimes,
        settings.dedup_mode,
        sha,
        result["elapsed_seconds"],
    )
    return result


def silver_totals(engine: Engine) -> Dict[str, int]:
    stmt = select(SilverCrimes.cantidad)
    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()
    return {"rows": len(rows), "total_crimes": int(sum(r[0] for r in rows))}
