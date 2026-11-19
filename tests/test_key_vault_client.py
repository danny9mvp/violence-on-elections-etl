from __future__ import annotations

import builtins
import sys
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy.engine import URL

from violence_etl.clients.key_vault import KeyVaultClient
from violence_etl.config import settings as settings_module
from violence_etl.config.settings import (
    Settings,
    database_url,
    database_url_display,
    database_url_object,
    postgres_url_from_key_vault,
)

PG_SECRETS = {
    "PGHOST": "db.example.postgres.database.azure.com",
    "PGPORT": "5432",
    "PGUSER": "etl_user",
    "PGPASSWORD": "s3cret%",
    "PGDATABASE": "violence",
}


class FakeSecretClient:
    def __init__(self, values):
        self._values = values
        self.requested = []

    def get_secret(self, name):
        self.requested.append(name)
        return SimpleNamespace(value=self._values.get(name))


def block_imports(monkeypatch, *blocked):
    real_import = builtins.__import__

    def guarded_import(name, global_ns=None, local_ns=None, fromlist=(), level=0):
        if any(name == item or name.startswith(item + ".") for item in blocked):
            raise AssertionError("Unexpected import: {0}".format(name))
        return real_import(name, global_ns, local_ns, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def make_settings(env="PROD", vault_url="https://vault.example/"):
    return Settings(
        env=env,
        sqlite_path="data/warehouse/violence_staging.db",
        source_url="http://example.test/export.csv",
        log_level="INFO",
        dedup_mode="drop",
        bronze_dir="data/bronze",
        key_vault_url=vault_url,
    )


def inject_fake_secrets(monkeypatch, fake_client):
    monkeypatch.setattr(
        "violence_etl.clients.key_vault.KeyVaultClient",
        lambda vault_url: KeyVaultClient(vault_url, secret_client=fake_client),
    )


def test_injected_secret_client_needs_no_azure_imports(monkeypatch):
    block_imports(monkeypatch, "azure.identity", "azure.keyvault.secrets")
    fake_client = FakeSecretClient({"API_TOKEN": "token-value"})

    client = KeyVaultClient("https://vault.example/", secret_client=fake_client)

    assert client.get_secret("API_TOKEN") == "token-value"
    assert fake_client.requested == ["API_TOKEN"]


def test_injected_credential_is_used_by_lazy_secret_client(monkeypatch):
    calls = {}

    class FakeSecretClientFactory:
        def __init__(self, vault_url, credential):
            calls["vault_url"] = vault_url
            calls["credential"] = credential

    azure_module = ModuleType("azure")
    keyvault_module = ModuleType("azure.keyvault")
    secrets_module = ModuleType("azure.keyvault.secrets")
    secrets_module.SecretClient = FakeSecretClientFactory
    keyvault_module.secrets = secrets_module
    azure_module.keyvault = keyvault_module

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.keyvault", keyvault_module)
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", secrets_module)
    block_imports(monkeypatch, "azure.identity")

    credential = object()
    client = KeyVaultClient("https://vault.example/", credential=credential)

    assert calls == {
        "vault_url": "https://vault.example/",
        "credential": credential,
    }
    assert client.vault_url == "https://vault.example/"


def test_missing_azure_packages_keep_import_error(monkeypatch):
    real_import = builtins.__import__

    def missing_azure(name, global_ns=None, local_ns=None, fromlist=(), level=0):
        if name == "azure" or name.startswith("azure."):
            raise ImportError("azure is not installed")
        return real_import(name, global_ns, local_ns, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_azure)

    with pytest.raises(ImportError) as exc:
        KeyVaultClient("https://vault.example/")
    assert "azure-identity" in str(exc.value)
    assert "azure-keyvault-secrets" in str(exc.value)


@pytest.mark.parametrize("value", ["", None])
def test_get_secret_rejects_empty_and_missing_values(value):
    fake_client = FakeSecretClient({"TOKEN": value})
    client = KeyVaultClient("https://vault.example/", secret_client=fake_client)

    with pytest.raises(ValueError) as exc:
        client.get_secret("TOKEN")
    assert str(exc.value) == "Key Vault secret 'TOKEN' is empty or missing"


def test_postgres_url_from_key_vault_builds_url_from_fake_secrets(monkeypatch):
    block_imports(monkeypatch, "azure.identity", "azure.keyvault.secrets")
    fake_client = FakeSecretClient(PG_SECRETS)
    inject_fake_secrets(monkeypatch, fake_client)

    url = postgres_url_from_key_vault("https://vault.example/")

    assert url.drivername == "postgresql+psycopg"
    assert url.host == PG_SECRETS["PGHOST"]
    assert url.port == 5432
    assert url.username == PG_SECRETS["PGUSER"]
    assert url.password == PG_SECRETS["PGPASSWORD"]
    assert url.database == PG_SECRETS["PGDATABASE"]
    assert url.query.get("sslmode") == "require"
    assert fake_client.requested == [
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
    ]


def test_invalid_port_keeps_existing_error(monkeypatch):
    fake_client = FakeSecretClient(dict(PG_SECRETS, PGPORT="not-a-port"))
    inject_fake_secrets(monkeypatch, fake_client)

    with pytest.raises(ValueError) as exc:
        postgres_url_from_key_vault("https://vault.example/")
    assert str(exc.value) == "Key Vault secret PGPORT must be an integer"


def test_postgres_url_from_key_vault_requires_vault_url():
    with pytest.raises(ValueError) as exc:
        postgres_url_from_key_vault("")
    assert str(exc.value) == "AZURE_KEYVAULT_URL is required when ENV=PROD"


def test_dev_and_test_url_building_does_not_import_key_vault_client(monkeypatch):
    block_imports(monkeypatch, "violence_etl.clients.key_vault")

    for env in ("DEV", "TEST"):
        url = database_url_object(make_settings(env=env, vault_url=None))
        assert url.get_backend_name() == "sqlite"


def test_database_url_display_masks_password(monkeypatch):
    captured = {}
    url = URL.create(
        "postgresql+psycopg",
        username=PG_SECRETS["PGUSER"],
        password=PG_SECRETS["PGPASSWORD"],
        host=PG_SECRETS["PGHOST"],
        port=5432,
        database=PG_SECRETS["PGDATABASE"],
        query={"sslmode": "require"},
    )

    def fake_fetch(vault_url):
        captured["vault_url"] = vault_url
        return url

    monkeypatch.setattr(settings_module, "postgres_url_from_key_vault", fake_fetch)
    settings = make_settings()

    assert "s3cret" in database_url(settings)
    assert "s3cret" not in database_url_display(settings)
    assert "***" in database_url_display(settings)
    assert captured["vault_url"] == "https://vault.example/"
