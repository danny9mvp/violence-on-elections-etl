from __future__ import annotations

import dataclasses

from sqlalchemy import func, select

from violence_etl.db.models.silver_crimes import SilverCrimes
from violence_etl.db.models.silver_rejected_rows import SilverRejectedRows
from violence_etl.transformations.bronze import ingest_bronze
from violence_etl.transformations.silver import build_silver

HEADER = '"FECHA HECHO","COD_DEPTO","DEPARTAMENTO","COD_MUNI","MUNICIPIO","ZONA","CANTIDAD"\n'


def _write(tmp_path, rows, name="case.csv"):
    path = tmp_path / name
    path.write_text(HEADER + "".join(rows))
    return str(path)


def build_via(engine, settings, path):
    ingest_bronze(engine, settings, csv_path=path)
    return build_silver(engine, settings)


def _rows(engine, model=SilverCrimes):
    with engine.connect() as conn:
        return conn.execute(select(model)).fetchall()


def _reasons(engine):
    with engine.connect() as conn:
        return dict(
            conn.execute(
                select(SilverRejectedRows.reject_reason, func.count())
                .group_by(SilverRejectedRows.reject_reason)
            ).fetchall()
        )


def test_sample_counts(sqlite_engine, settings_sqlite, sample_csv):
    result = build_via(sqlite_engine, settings_sqlite, sample_csv)
    assert result["raw_rows"] == 40
    assert result["silver_rows"] == 32
    assert result["rejected_rows"] == 0
    assert result["dropped_duplicates"] == 8
    assert result["total_crimes"] == 40


def test_r1_strip_and_r2_upper(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['" 15/06/2014 ","05","  antioquia ","05001"," medellin "," urbana ","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.departamento == "ANTIOQUIA"
    assert row.municipio == "MEDELLIN"
    assert row.zona == "URBANA"


def test_r3_zero_padding_preserved(sqlite_engine, settings_sqlite, tmp_path):
    # "5" / "5660" must be zero padded to "05" / "05660" and stay text.
    path = _write(
        tmp_path,
        ['"15/06/2014","5","ANTIOQUIA","5660","RIONEGRO","RURAL","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.cod_depto == "05"
    assert row.cod_muni == "05660"
    assert isinstance(row.cod_depto, str)
    assert len(row.cod_depto) == 2
    assert len(row.cod_muni) == 5


def test_r4_edge_date_parses(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"31/08/2026","11","BOGOTA","11001","BOGOTA","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.fecha_hecho.isoformat() == "2026-08-31"


def test_r4_dd_mm_not_mm_dd(sqlite_engine, settings_sqlite, tmp_path):
    # 11/12/2024 must be 11 December, never 12 November.
    path = _write(
        tmp_path,
        ['"11/12/2024","11","BOGOTA","11001","BOGOTA","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.fecha_hecho.isoformat() == "2024-12-11"
    assert (row.month, row.year) == (12, 2024)


def test_r5_cantidad_is_integer(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.cantidad == 1
    assert isinstance(row.cantidad, int)


def test_r6_bad_zona_rejected(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","SEMIURBANA","1"\n'],
    )
    out = build_via(sqlite_engine, settings_sqlite, path)
    assert out["rejected_rows"] == 1
    assert _reasons(sqlite_engine) == {"bad_zona": 1}


def test_r8_depto_muni_mismatch_rejected(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","11001","BOGOTA","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    assert _reasons(sqlite_engine) == {"depto_muni_mismatch": 1}


def test_empty_code_is_null_field_not_type_error(sqlite_engine, settings_sqlite, tmp_path):
    # R3 must leave empty codes for R7 (docstring agreement).
    path = _write(
        tmp_path,
        ['"15/06/2014","","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'],
    )
    out = build_via(sqlite_engine, settings_sqlite, path)
    assert out["rejected_rows"] == 1
    assert _reasons(sqlite_engine) == {"null_field": 1}


def test_empty_muni_code_is_null_field(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","","MEDELLIN","URBANA","1"\n'],
    )
    out = build_via(sqlite_engine, settings_sqlite, path)
    assert out["rejected_rows"] == 1
    assert _reasons(sqlite_engine) == {"null_field": 1}


def test_fractional_cantidad_rejected(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1.5"\n'],
    )
    out = build_via(sqlite_engine, settings_sqlite, path)
    assert out["rejected_rows"] == 1
    assert _reasons(sqlite_engine) == {"bad_cantidad": 1}


def test_r9_sum_mode_sums_instead(sqlite_engine, settings_sqlite, tmp_path):
    row = '"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'
    path = _write(tmp_path, [row, row, row])
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=path)
    settings_sum = dataclasses.replace(settings_sqlite, dedup_mode="sum")
    out = build_silver(sqlite_engine, settings_sum)
    assert out["silver_rows"] == 1
    assert out["total_crimes"] == 3
    stored = _rows(sqlite_engine)[0]
    assert stored.cantidad == 3


def test_sum_mode_reproduces_total_on_sample(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    settings_sum = dataclasses.replace(settings_sqlite, dedup_mode="sum")
    out = build_silver(sqlite_engine, settings_sum)
    assert out["silver_rows"] == 32
    assert out["total_crimes"] == 40


def test_r10_rejected_reasons_on_bad_fixture(sqlite_engine, settings_sqlite, bad_csv):
    out = build_via(sqlite_engine, settings_sqlite, bad_csv)
    assert out["raw_rows"] == 12
    assert out["silver_rows"] == 0
    assert out["rejected_rows"] == 12
    reasons = _reasons(sqlite_engine)
    assert reasons.get("null_field") == 5
    assert reasons.get("bad_cod_depto") == 1
    assert reasons.get("bad_cod_muni") == 1
    assert reasons.get("bad_zona") == 1
    assert reasons.get("depto_muni_mismatch") == 1
    assert reasons.get("bad_date") == 1
    assert reasons.get("bad_cantidad") == 2


def test_rejected_rows_keep_raw_values(sqlite_engine, settings_sqlite, bad_csv):
    build_via(sqlite_engine, settings_sqlite, bad_csv)
    with sqlite_engine.connect() as conn:
        row = conn.execute(
            select(SilverRejectedRows.raw_values).where(
                SilverRejectedRows.reject_reason == "bad_zona"
            )
        ).first()
    assert '"ZONA": "SEMIURBANA"' in row[0]


def test_r11_calendar_columns(sqlite_engine, settings_sqlite, tmp_path):
    # 2024-12-11 is a Wednesday (ISO 3).
    path = _write(
        tmp_path,
        ['"11/12/2024","11","BOGOTA","11001","BOGOTA","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert (row.year, row.month, row.quarter) == (2024, 12, 4)
    assert row.weekday_num == 3
    assert row.weekday_name == "Wednesday"


def test_r12_electoral_period(sqlite_engine, settings_sqlite, tmp_path):
    path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'],
    )
    build_via(sqlite_engine, settings_sqlite, path)
    row = _rows(sqlite_engine)[0]
    assert row.electoral_period == "electoral"


def test_r13_row_hash_and_sha(sqlite_engine, settings_sqlite, sample_csv):
    out = build_via(sqlite_engine, settings_sqlite, sample_csv)
    rows = _rows(sqlite_engine)
    assert all(len(r.row_hash) == 64 for r in rows)
    assert all(r.source_sha256 == out["source_sha256"] for r in rows)
    assert all(r.silver_loaded_at is not None for r in rows)


def test_silver_rerun_is_idempotent(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    first = build_silver(sqlite_engine, settings_sqlite)
    second = build_silver(sqlite_engine, settings_sqlite)
    assert first["silver_rows"] == second["silver_rows"] == 32
    with sqlite_engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(SilverCrimes)).scalar()
    assert int(count) == 32


def test_inserted_rows_track_actual_writes(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    first = build_silver(sqlite_engine, settings_sqlite)
    second = build_silver(sqlite_engine, settings_sqlite)
    # The first run writes all rows; the second conflicts with every row.
    assert first["inserted_rows"] == 32
    assert second["inserted_rows"] == 0
    # Reported totals describe what the database holds, not the in-memory frame.
    assert first["silver_rows"] == second["silver_rows"] == 32


def test_rejected_rows_track_actual_writes(sqlite_engine, settings_sqlite, bad_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=bad_csv)
    first = build_silver(sqlite_engine, settings_sqlite)
    second = build_silver(sqlite_engine, settings_sqlite)
    assert first["rejected_rows"] == second["rejected_rows"] == 12
    with sqlite_engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(SilverRejectedRows)
        ).scalar()
    assert int(count) == 12


def test_new_snapshot_replaces_previous(sqlite_engine, settings_sqlite, tmp_path):
    first_path = _write(
        tmp_path,
        ['"15/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'],
        name="first.csv",
    )
    build_via(sqlite_engine, settings_sqlite, first_path)
    second_path = _write(
        tmp_path,
        ['"16/06/2014","05","ANTIOQUIA","05001","MEDELLIN","URBANA","2"\n'],
        name="second.csv",
    )
    out = build_via(sqlite_engine, settings_sqlite, second_path)
    # Silver holds only the active snapshot; the old sha is purged.
    assert out["silver_rows"] == 1
    with sqlite_engine.connect() as conn:
        shas = [
            r[0]
            for r in conn.execute(select(SilverCrimes.source_sha256).distinct())
        ]
    assert shas == [out["source_sha256"]]
