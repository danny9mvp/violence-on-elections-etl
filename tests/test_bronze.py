from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from violence_etl.bronze import ingest_bronze
from violence_etl.errors import SchemaError
from violence_etl.io import read_csv, sha256_file
from violence_etl.models import BronzeCrimesRaw, BronzeIngestionLog
from violence_etl.schema import EXPECTED_HEADER, validate_header


def _count(engine, model):
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(model)).scalar())


def test_ingest_loads_all_rows(sqlite_engine, settings_sqlite, sample_csv):
    result = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    assert result["status"] == "loaded"
    assert result["raw_rows"] == 40
    assert _count(sqlite_engine, BronzeCrimesRaw) == 40


def test_ingest_uses_content_hash(sqlite_engine, settings_sqlite, sample_csv):
    result = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    assert result["source_sha256"] == sha256_file(sample_csv)
    assert len(result["source_sha256"]) == 64


def test_landing_file_written_by_hash(sqlite_engine, settings_sqlite, sample_csv):
    result = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    landing = os.path.join(
        settings_sqlite.bronze_dir, "landing", result["source_sha256"] + ".csv"
    )
    assert os.path.exists(landing)
    assert sha256_file(landing) == result["source_sha256"]


def test_reingest_same_sha_skips(sqlite_engine, settings_sqlite, sample_csv):
    first = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    second = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    assert first["status"] == "loaded"
    assert second["status"] == "skipped"
    assert _count(sqlite_engine, BronzeCrimesRaw) == 40
    assert _count(sqlite_engine, BronzeIngestionLog) == 1


def test_force_reloads(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    out = ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv, force=True)
    assert out["status"] == "loaded"
    assert _count(sqlite_engine, BronzeCrimesRaw) == 40


def test_keep_default_na_keeps_empty_strings(sqlite_engine, settings_sqlite, bad_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=bad_csv)
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            select(BronzeCrimesRaw.municipio_raw, BronzeCrimesRaw.cantidad_raw).where(
                BronzeCrimesRaw.row_num == 5
            )
        ).first()
    # Row 5 has an empty MUNICIPIO; it must be "" not None.
    assert rows[0] == ""
    assert rows[1] == "1"


def test_raw_fields_are_text(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    with sqlite_engine.connect() as conn:
        corr = conn.execute(
            select(BronzeCrimesRaw.cod_depto_raw, BronzeCrimesRaw.cantidad_raw)
            .where(BronzeCrimesRaw.row_num == 1)
        ).first()
    assert corr[0] == "05"
    assert corr[1] == "1"
    assert isinstance(corr[0], str)


def test_row_num_is_sequential(sqlite_engine, settings_sqlite, sample_csv):
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    with sqlite_engine.connect() as conn:
        nums = [
            r[0]
            for r in conn.execute(
                select(BronzeCrimesRaw.row_num).order_by(BronzeCrimesRaw.row_num)
            )
        ]
    assert nums == list(range(1, 41))


def test_header_validation_ok():
    validate_header(EXPECTED_HEADER)


def test_header_validation_raises_on_mismatch():
    with pytest.raises(SchemaError):
        validate_header(["FECHA HECHO", "COD_DEPTO"])


def test_header_validation_raises_on_case_change():
    bad = list(EXPECTED_HEADER)
    bad[0] = "fecha hecho"
    with pytest.raises(SchemaError):
        validate_header(bad)


def test_read_csv_preserves_empty_string(bad_csv):
    df = read_csv(bad_csv)
    assert len(df) == 12
    assert list(df.columns) == list(EXPECTED_HEADER)
    assert df.iloc[0]["FECHA HECHO"] == ""


def test_ingest_wrong_header_raises(sqlite_engine, settings_sqlite, tmp_path):
    bad = tmp_path / "wrong.csv"
    bad.write_text('"A","B"\n"1","2"\n')
    with pytest.raises(SchemaError):
        ingest_bronze(sqlite_engine, settings_sqlite, csv_path=str(bad))
