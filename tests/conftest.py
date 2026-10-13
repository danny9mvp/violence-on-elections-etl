"""Shared pytest fixtures.

The environment-clearing fixture keeps configuration tests independent from
whatever ``.env`` or shell variables happen to exist on the developer machine.
"""
from __future__ import annotations

import os

import pytest

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
