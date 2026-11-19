from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from violence_etl.config.settings import get_settings
from violence_etl.db.connection import make_engine
from violence_etl.db.models.bronze_crimes_raw import BronzeCrimesRaw
from violence_etl.db.models.bronze_ingestion_log import BronzeIngestionLog
from violence_etl.db.models.gold_crimes_by_calendar import GoldCrimesByCalendar
from violence_etl.db.models.gold_crimes_by_department import GoldCrimesByDepartment
from violence_etl.db.models.gold_crimes_by_electoral_period import GoldCrimesByElectoralPeriod
from violence_etl.db.models.gold_top_50_departments import GoldTop5Departments
from violence_etl.db.models.silver_crimes import SilverCrimes
from violence_etl.db.models.silver_rejected_rows import SilverRejectedRows
from violence_etl.pipeline import run_all

TABLES = [
    BronzeCrimesRaw,
    BronzeIngestionLog,
    SilverCrimes,
    SilverRejectedRows,
    GoldTop5Departments,
    GoldCrimesByDepartment,
    GoldCrimesByCalendar,
    GoldCrimesByElectoralPeriod,
]


def _count(engine, model):
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(model)).scalar())


def _all_counts(engine):
    return {model.__tablename__: _count(engine, model) for model in TABLES}


def _integ_engine(tmp_path, monkeypatch):
    db_path = tmp_path / "integration.db"
    monkeypatch.setenv("ENV", "TEST")
    monkeypatch.setenv("ETL_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("ETL_BRONZE_DIR", str(tmp_path / "bronze"))
    settings = get_settings()
    engine = make_engine(settings=settings)
    from violence_etl.db.models.base_model import Base

    Base.metadata.create_all(engine)
    return engine, settings


def test_run_all_against_sqlite(tmp_path, monkeypatch, sample_csv):
    engine, settings = _integ_engine(tmp_path, monkeypatch)

    result = run_all(engine, settings, csv_path=sample_csv)
    silver = result["silver"]
    gold = result["gold"]

    assert result["bronze"]["raw_rows"] == 40
    assert silver["silver_rows"] == 32
    assert silver["dropped_duplicates"] == 8
    assert silver["total_crimes"] == 40
    assert _count(engine, BronzeCrimesRaw) == 40
    assert _count(engine, SilverCrimes) == 32
    assert _count(engine, SilverRejectedRows) == 0
    assert gold["gold_top5_departments"] == 5
    assert gold["gold_crimes_by_department"] == 5
    assert gold["gold_crimes_by_electoral_period"] == 4
    assert gold["grand_total"] == 40


def test_run_all_is_idempotent(tmp_path, monkeypatch, sample_csv):
    engine, settings = _integ_engine(tmp_path, monkeypatch)

    run_all(engine, settings, csv_path=sample_csv)
    first = _all_counts(engine)
    run_all(engine, settings, csv_path=sample_csv)
    second = _all_counts(engine)

    assert first == second
    assert second["bronze_crimes_raw"] == 40
    assert second["bronze_ingestion_log"] == 1
    assert second["silver_crimes"] == 32
    assert second["silver_rejected_rows"] == 0


def test_run_all_is_idempotent_with_rejected_rows(tmp_path, monkeypatch, bad_csv):
    engine, settings = _integ_engine(tmp_path, monkeypatch)

    run_all(engine, settings, csv_path=bad_csv)
    first = _all_counts(engine)
    run_all(engine, settings, csv_path=bad_csv)
    second = _all_counts(engine)

    # Both tables named in the assignment (log + rejects) stay stable.
    assert first == second
    assert second["bronze_ingestion_log"] == 1
    assert second["silver_crimes"] == 0
    assert second["silver_rejected_rows"] == 12


def test_grand_totals_agree(tmp_path, monkeypatch, sample_csv):
    engine, settings = _integ_engine(tmp_path, monkeypatch)
    run_all(engine, settings, csv_path=sample_csv)

    silver_total = int(
        engine.connect()
        .execute(select(func.coalesce(func.sum(SilverCrimes.cantidad), 0)))
        .scalar()
    )
    dept_total = int(
        engine.connect()
        .execute(select(func.coalesce(func.sum(GoldCrimesByDepartment.total_crimes), 0)))
        .scalar()
    )
    period_total = int(
        engine.connect()
        .execute(
            select(func.coalesce(func.sum(GoldCrimesByElectoralPeriod.total_crimes), 0))
        )
        .scalar()
    )
    assert silver_total == dept_total == period_total == 40


def test_rejected_rows_then_gold(tmp_path, monkeypatch, bad_csv):
    engine, settings = _integ_engine(tmp_path, monkeypatch)
    result = run_all(engine, settings, csv_path=bad_csv)
    assert result["silver"]["rejected_rows"] == 12
    assert result["silver"]["silver_rows"] == 0
    assert _count(engine, SilverRejectedRows) == 12
    # Gold on an empty silver is still built (empty tables), not an error.
    assert result["gold"]["grand_total"] == 0


def test_cli_init_db_and_run_all(tmp_path, monkeypatch, sample_csv, capsys):
    from violence_etl.cli import main

    db_path = tmp_path / "cli.db"
    bronze_dir = tmp_path / "bronze"
    monkeypatch.setenv("ETL_BRONZE_DIR", str(bronze_dir))
    monkeypatch.setenv("ENV", "TEST")

    base = ["--sqlite-path", str(db_path)]
    assert main(base + ["init-db"]) == 0
    assert main(base + ["run-all", "--csv-path", sample_csv]) == 0
    assert main(base + ["validate"]) == 0
    out = capsys.readouterr().out
    assert "validate: PASS" in out


def test_cli_drop_db_requires_yes(tmp_path, monkeypatch, sample_csv):
    from sqlalchemy import inspect

    from violence_etl.cli import main
    from violence_etl.db.models.base_model import Base

    db_path = tmp_path / "cli2.db"
    monkeypatch.setenv("ENV", "TEST")
    base = ["--sqlite-path", str(db_path)]
    assert main(base + ["init-db"]) == 0
    assert main(base + ["drop-db"]) == 2
    assert main(base + ["drop-db", "--yes"]) == 0

    # drop-db must leave a fully recreated schema, not just alembic_version.
    engine = make_engine("sqlite:///" + str(db_path))
    try:
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert expected <= names, "missing after drop-db: {0}".format(expected - names)


@pytest.mark.full_dataset
@pytest.mark.skipif(
    os.environ.get("ETL_FULL_DATASET") != "1",
    reason="set ETL_FULL_DATASET=1 to run against the real dataset",
)
def test_full_dataset_counts(tmp_path, monkeypatch):
    engine, settings = _integ_engine(tmp_path, monkeypatch)
    result = run_all(engine, settings)
    assert result["bronze"]["raw_rows"] == 15696
    assert result["silver"]["silver_rows"] == 14212
    assert result["silver"]["dropped_duplicates"] == 1484
    assert result["silver"]["total_crimes"] == 14212
    assert result["gold"]["gold_crimes_by_department"] == 32
    assert result["gold"]["gold_top5_departments"] == 5
    assert result["gold"]["gold_crimes_by_electoral_period"] == 4
