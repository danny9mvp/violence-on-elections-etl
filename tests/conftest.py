"""Shared pytest fixtures.

The environment-clearing fixture keeps configuration tests independent from
whatever ``.env`` or shell variables happen to exist on the developer machine.
"""
from __future__ import annotations

import os

import pytest

from violence_etl.db import make_engine
from violence_etl.models import Base

_ETL_ENV_KEYS = (
    "ETL_DB_BACKEND",
    "ETL_SQLITE_PATH",
    "ETL_SOURCE_URL",
    "ETL_LOG_LEVEL",
    "ETL_DEDUP_MODE",
    "ETL_BRONZE_DIR",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def clean_etl_env(monkeypatch):
    """Remove ETL/PG env vars so defaults are deterministic in every test."""
    for key in _ETL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def sqlite_engine(tmp_path):
    """A fresh file-backed SQLite engine with every table created."""
    db_path = tmp_path / "test.db"
    engine = make_engine("sqlite:///" + str(db_path))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def settings_sqlite(sqlite_engine, monkeypatch, tmp_path):
    """Settings pointed at the temp SQLite database and a temp bronze dir."""
    from violence_etl.settings import get_settings

    monkeypatch.setenv("ETL_DB_BACKEND", "sqlite")
    monkeypatch.setenv("ETL_SQLITE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ETL_BRONZE_DIR", str(tmp_path / "bronze"))
    monkeypatch.setenv("ETL_DEDUP_MODE", "drop")
    return get_settings()


@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_csv(fixtures_dir):
    return os.path.join(fixtures_dir, "yi5j-5fe9_sample.csv")


@pytest.fixture
def bad_csv(fixtures_dir):
    return os.path.join(fixtures_dir, "yi5j-5fe9_bad.csv")


@pytest.fixture
def many_depts_csv(fixtures_dir):
    return os.path.join(fixtures_dir, "yi5j-5fe9_many_depts.csv")
