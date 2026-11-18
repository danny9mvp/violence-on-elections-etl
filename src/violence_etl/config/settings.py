"""Environment-driven configuration module.

``ENV`` selects the runtime target:
- ``DEV`` / ``TEST``: SQLite (local dev and automated tests)
- ``PROD``: Azure PostgreSQL, with credentials fetched from Azure Key Vault

PostgreSQL credentials are not read from local environment variables; in PROD
they come only from Key Vault via DefaultAzureCredential.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

DEFAULT_SOURCE_URL = "http://www.datos.gov.co/api/v3/views/yi5j-5fe9/export.csv"
DEFAULT_SQLITE_PATH = "data/warehouse/violence_staging.db"
VALID_ENVS = ("DEV", "TEST", "PROD")


@dataclass(frozen=True)
class Settings:
    env: str              # "DEV" | "TEST" | "PROD"
    sqlite_path: str
    source_url: str
    log_level: str
    dedup_mode: str       # "drop" | "sum"
    bronze_dir: str
    key_vault_url: Optional[str] = field(default=None, repr=False)

    @property
    def is_sqlite(self) -> bool:
        return self.env in ("DEV", "TEST")


def _env(key: str, default: str) -> str:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return value


def _normalize_env(value: str) -> str:
    env = (value or "DEV").strip().upper()
    if env not in VALID_ENVS:
        raise ValueError("ENV must be one of: {0}".format(", ".join(VALID_ENVS)))
    return env


def get_settings() -> Settings:
    env = _normalize_env(_env("ENV", "DEV"))
    key_vault_url = os.environ.get("AZURE_KEYVAULT_URL") or None
    if env == "PROD" and not key_vault_url:
        raise ValueError("AZURE_KEYVAULT_URL is required when ENV=PROD")
    return Settings(
        env=env,
        sqlite_path=_env("ETL_SQLITE_PATH", DEFAULT_SQLITE_PATH),
        source_url=_env("ETL_SOURCE_URL", DEFAULT_SOURCE_URL),
        log_level=_env("ETL_LOG_LEVEL", "INFO"),
        dedup_mode=_env("ETL_DEDUP_MODE", "drop"),
        bronze_dir=_env("ETL_BRONZE_DIR", "data/bronze"),
        key_vault_url=key_vault_url,
    )


def database_url_object(settings: Optional[Settings] = None) -> URL:
    """Build a :class:`sqlalchemy.engine.URL` for the configured environment.

    DEV/TEST return a SQLite URL. PROD fetches PostgreSQL credentials from
    Azure Key Vault and returns a URL with sslmode=require.
    """
    s = settings or get_settings()
    if s.is_sqlite:
        return URL.create("sqlite", database=s.sqlite_path)

    from violence_etl.config.keyvault import postgres_url_from_key_vault

    return postgres_url_from_key_vault(s.key_vault_url or "")


def database_url(settings: Optional[Settings] = None) -> str:
    """Render the connection URL as a string with the password visible."""
    return database_url_object(settings).render_as_string(hide_password=False)


def database_url_display(settings: Optional[Settings] = None) -> str:
    """Like :func:`database_url` but with the password masked for logging."""
    return database_url_object(settings).render_as_string(hide_password=True)
