from __future__ import annotations

import pytest

from violence_etl.settings import (
    DEFAULT_SOURCE_URL,
    DEFAULT_SQLITE_PATH,
    database_url,
    get_settings,
)


def test_defaults_when_env_is_empty():
    s = get_settings()
    assert s.backend == "postgres"
    assert s.pg_host == "localhost"
    assert s.pg_port == 5432
    assert s.pg_user == "postgres"
    assert s.pg_password == "postgres"
    assert s.pg_database == "violence"
    assert s.sqlite_path == DEFAULT_SQLITE_PATH
    assert s.source_url == DEFAULT_SOURCE_URL
    assert s.log_level == "INFO"
    assert s.dedup_mode == "drop"
    assert s.bronze_dir == "data/bronze"
    assert s.database_url_override is None


def test_default_database_url_is_psycopg3_postgres():
    url = database_url(get_settings())
    assert url == "postgresql+psycopg://postgres:postgres@localhost:5432/violence"


def test_sqlite_backend_builds_sqlite_url(monkeypatch):
    monkeypatch.setenv("ETL_DB_BACKEND", "sqlite")
    monkeypatch.setenv("ETL_SQLITE_PATH", "/tmp/x.db")
    s = get_settings()
    assert s.backend == "sqlite"
    assert database_url(s) == "sqlite:////tmp/x.db"


def test_overrides_via_env(monkeypatch):
    monkeypatch.setenv("PGHOST", "db.internal")
    monkeypatch.setenv("PGPORT", "6543")
    monkeypatch.setenv("PGUSER", "etl")
    monkeypatch.setenv("PGPASSWORD", "secret")
    monkeypatch.setenv("PGDATABASE", "warehouse")
    monkeypatch.setenv("ETL_DEDUP_MODE", "sum")
    monkeypatch.setenv("ETL_LOG_LEVEL", "DEBUG")
    s = get_settings()
    assert s.pg_host == "db.internal"
    assert s.pg_port == 6543
    assert s.dedup_mode == "sum"
    assert s.log_level == "DEBUG"
    assert database_url(s) == "postgresql+psycopg://etl:secret@db.internal:6543/warehouse"


def test_invalid_port_raises(monkeypatch):
    monkeypatch.setenv("PGPORT", "not-a-number")
    with pytest.raises(ValueError):
        get_settings()


def test_database_url_override_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///override.db")
    s = get_settings()
    assert s.backend == "sqlite"
    assert database_url(s) == "sqlite:///override.db"


def test_database_url_override_postgres_infers_backend(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    s = get_settings()
    assert s.backend == "postgres"
    assert database_url(s) == "postgresql+psycopg://u:p@h:5432/d"


def test_settings_is_frozen():
    s = get_settings()
    with pytest.raises(Exception):
        s.backend = "sqlite"  # type: ignore[misc]
