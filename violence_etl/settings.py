"""Single env-driven configuration module.

Defaults match the required PostgreSQL warehouse credentials. The whole ETL
can run against SQLite with no PostgreSQL instance by exporting
``ETL_DB_BACKEND=sqlite``. A full ``DATABASE_URL`` may also be supplied and
then takes precedence over the individual pieces.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SOURCE_URL = "http://www.datos.gov.co/api/v3/views/yi5j-5fe9/export.csv"
DEFAULT_SQLITE_PATH = "data/warehouse/violence_staging.db"


@dataclass(frozen=True)
class Settings:
    backend: str          # "postgres" | "sqlite"
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str
    sqlite_path: str
    source_url: str
    log_level: str
    dedup_mode: str       # "drop" | "sum"
    bronze_dir: str
    database_url_override: Optional[str] = None


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _infer_backend(explicit: str, override: Optional[str]) -> str:
    if explicit:
        return explicit.strip().lower()
    if override:
        scheme = override.split(":", 1)[0].lower()
        if scheme.startswith("sqlite"):
            return "sqlite"
        if scheme.startswith("postgres"):
            return "postgres"
    return "postgres"


def get_settings() -> Settings:
    override = os.environ.get("DATABASE_URL") or None
    backend = _infer_backend(_env("ETL_DB_BACKEND", ""), override)
    return Settings(
        backend=backend,
        pg_host=_env("PGHOST", "localhost"),
        pg_port=int(_env("PGPORT", "5432")),
        pg_user=_env("PGUSER", "postgres"),
        pg_password=_env("PGPASSWORD", "postgres"),
        pg_database=_env("PGDATABASE", "violence"),
        sqlite_path=_env("ETL_SQLITE_PATH", DEFAULT_SQLITE_PATH),
        source_url=_env("ETL_SOURCE_URL", DEFAULT_SOURCE_URL),
        log_level=_env("ETL_LOG_LEVEL", "INFO"),
        dedup_mode=_env("ETL_DEDUP_MODE", "drop"),
        bronze_dir=_env("ETL_BRONZE_DIR", "data/bronze"),
        database_url_override=override,
    )


def database_url(settings: Optional[Settings] = None) -> str:
    s = settings or get_settings()
    if s.database_url_override:
        return s.database_url_override
    if s.backend == "sqlite":
        return "sqlite:///" + s.sqlite_path
    return "postgresql+psycopg://{u}:{p}@{h}:{port}/{d}".format(
        u=s.pg_user, p=s.pg_password, h=s.pg_host, port=s.pg_port, d=s.pg_database
    )
