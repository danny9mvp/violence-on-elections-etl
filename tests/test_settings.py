from __future__ import annotations

import pytest
from sqlalchemy.engine import URL

from violence_etl.config.settings import (
    DEFAULT_SOURCE_URL,
    DEFAULT_SQLITE_PATH,
    database_url,
    database_url_display,
    database_url_object,
    get_settings,
)


def test_defaults_to_dev_sqlite():
    s = get_settings()
    assert s.env == "DEV"
    assert s.is_sqlite is True
    assert s.sqlite_path == DEFAULT_SQLITE_PATH
    assert s.source_url == DEFAULT_SOURCE_URL
    assert s.log_level == "INFO"
    assert s.dedup_mode == "drop"
    assert s.bronze_dir == "data/bronze"
    assert s.key_vault_url is None
    assert s.blob_storage is None


def test_dev_and_test_build_sqlite_url(monkeypatch, tmp_path):
    db = str(tmp_path / "x.db")
    monkeypatch.setenv("ETL_SQLITE_PATH", db)
    for env in ("DEV", "TEST", "dev", " test "):
        monkeypatch.setenv("ENV", env)
        s = get_settings()
        assert s.env == env.strip().upper()
        assert database_url_object(s).render_as_string(hide_password=False) == "sqlite:///" + db


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("ENV", "STAGING")
    with pytest.raises(ValueError):
        get_settings()


def test_prod_requires_key_vault_url(monkeypatch):
    monkeypatch.setenv("ENV", "PROD")
    monkeypatch.delenv("AZURE_KEYVAULT_URL", raising=False)
    with pytest.raises(ValueError):
        get_settings()


def test_prod_fetches_postgres_url_from_key_vault(monkeypatch):
    monkeypatch.setenv("ENV", "PROD")
    monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://violencekv.vault.azure.net/")

    captured = {}
    blob_captured = {}

    def fake_fetch(vault_url):
        captured["vault_url"] = vault_url
        return URL.create(
            "postgresql+psycopg",
            username="etl_user",
            password="s3cret%",
            host="db.example.postgres.database.azure.com",
            port=5432,
            database="violence",
            query={"sslmode": "require"},
        )

    def fake_blob_fetch(vault_url):
        blob_captured["vault_url"] = vault_url
        from violence_etl.config.settings import BlobStorageConfig

        return BlobStorageConfig(
            storage_account_name="acct",
            bronze_container="bronze",
            silver_container="silver",
            gold_container="gold",
        )

    monkeypatch.setattr(
        "violence_etl.config.settings.postgres_url_from_key_vault", fake_fetch
    )
    monkeypatch.setattr(
        "violence_etl.config.settings.blob_storage_config_from_key_vault",
        fake_blob_fetch,
    )
    s = get_settings()
    assert s.env == "PROD"
    assert s.is_sqlite is False
    assert blob_captured["vault_url"] == "https://violencekv.vault.azure.net/"
    assert s.blob_storage is not None
    assert s.blob_storage.storage_account_name == "acct"

    url = database_url_object(s)
    assert captured["vault_url"] == "https://violencekv.vault.azure.net/"
    assert url.host == "db.example.postgres.database.azure.com"
    assert url.query.get("sslmode") == "require"
    assert "s3cret" in database_url(s)
    assert "s3cret" not in database_url_display(s)
    assert "***" in database_url_display(s)


def test_settings_is_frozen():
    s = get_settings()
    with pytest.raises(Exception):
        s.env = "PROD"  # type: ignore[misc]
