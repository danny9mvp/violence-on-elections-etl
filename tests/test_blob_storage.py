from __future__ import annotations

import os
import re

import pytest

import violence_etl.db.models.silver_rejected_rows  # noqa: F401
from violence_etl.config.settings import (
    BlobStorageConfig,
    Settings,
    blob_storage_config_from_key_vault,
    get_settings,
)
from violence_etl.storage.blob_storage import BlobArtifactStorage
from violence_etl.storage.factory import get_artifact_storage
from violence_etl.storage.local_storage import (
    GOLD_CAL,
    GOLD_DEPT,
    GOLD_PERIOD,
    GOLD_TOP5,
    LocalArtifactStorage,
)
from violence_etl.transformations.bronze import ingest_bronze
from violence_etl.transformations.gold import build_gold
from violence_etl.utils import io as etl_io

BLOB_SECRETS = {
    "STORAGEACCOUNT": "acctprod",
    "BRZECONTAINER": "bronze-container",
    "SILVCONTAINER": "silver-container",
    "GOLDCONTAINER": "gold-container",
}


class FakeSecretClient:
    def __init__(self, values):
        self._values = values
        self.requested = []

    def get_secret(self, name):
        self.requested.append(name)
        value = self._values.get(name)
        if value is None or value == "":
            raise ValueError("Key Vault secret '{0}' is empty or missing".format(name))
        return value


class FakeDownload:
    def __init__(self, data):
        self._data = data

    def readall(self):
        return self._data


class FakeBlobClient:
    def __init__(self, store, container, name):
        self._store = store
        self._container = container
        self._name = name
        self.uploads = []

    @property
    def data(self):
        return self._store[self._container].get(self._name)

    def exists(self):
        return self._name in self._store[self._container]

    def upload_blob(self, data, overwrite=False):
        if not overwrite and self.exists():
            raise AssertionError("landing blob should not be overwritten")
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._store[self._container][self._name] = data
        self.uploads.append((self._name, data, overwrite))

    def download_blob(self):
        return FakeDownload(self._store[self._container][self._name])


class FakeContainerClient:
    def __init__(self, store, name):
        self._store = store
        self.name = name
        self.blobs = {}

    def get_blob_client(self, blob_name):
        client = self.blobs.get(blob_name)
        if client is None:
            client = FakeBlobClient(self._store, self.name, blob_name)
            self.blobs[blob_name] = client
        return client


class FakeBlobServiceClient:
    def __init__(self):
        self.store = {}
        self.containers = {}
        self.account_urls = []

    def add_container(self, name):
        self.store.setdefault(name, {})

    def get_container_client(self, name):
        self.store.setdefault(name, {})
        client = self.containers.get(name)
        if client is None:
            client = FakeContainerClient(self.store, name)
            self.containers[name] = client
        return client


def make_blob_config():
    return BlobStorageConfig(
        storage_account_name="acctprod",
        bronze_container="bronze-container",
        silver_container="silver-container",
        gold_container="gold-container",
    )


def make_prod_settings():
    return Settings(
        env="PROD",
        sqlite_path="data/warehouse/violence_staging.db",
        source_url="http://example.test/export.csv",
        log_level="INFO",
        dedup_mode="drop",
        bronze_dir="data/bronze",
        key_vault_url="https://vault.example/",
        blob_storage=make_blob_config(),
    )


def test_blob_storage_config_resolves_all_secrets():
    fake_client = FakeSecretClient(BLOB_SECRETS)
    config = blob_storage_config_from_key_vault("https://vault.example/", client=fake_client)
    assert config == make_blob_config()
    assert fake_client.requested == [
        "STORAGEACCOUNT",
        "BRZECONTAINER",
        "SILVCONTAINER",
        "GOLDCONTAINER",
    ]


@pytest.mark.parametrize("name", ["STORAGEACCOUNT", "BRZECONTAINER", "SILVCONTAINER", "GOLDCONTAINER"])
@pytest.mark.parametrize("value", ["", None])
def test_blob_storage_config_rejects_empty_or_missing(name, value):
    values = dict(BLOB_SECRETS)
    values[name] = value
    fake_client = FakeSecretClient(values)
    with pytest.raises(ValueError) as exc:
        blob_storage_config_from_key_vault("https://vault.example/", client=fake_client)
    assert str(exc.value) == "Key Vault secret '{0}' is empty or missing".format(name)


def test_prod_get_settings_fails_fast_on_missing_blob_secret(monkeypatch):
    monkeypatch.setenv("ENV", "PROD")
    monkeypatch.setenv("AZURE_KEYVAULT_URL", "https://vault.example/")
    values = dict(BLOB_SECRETS)
    values["GOLDCONTAINER"] = ""

    class Client:
        def __init__(self, vault_url, credential=None, secret_client=None):
            self.vault_url = vault_url
            self._secrets = values

        def get_secret(self, name):
            value = self._secrets.get(name)
            if value is None or value == "":
                raise ValueError("Key Vault secret '{0}' is empty or missing".format(name))
            return value

    monkeypatch.setattr("violence_etl.clients.key_vault.KeyVaultClient", Client)
    with pytest.raises(ValueError) as exc:
        get_settings()
    assert str(exc.value) == "Key Vault secret 'GOLDCONTAINER' is empty or missing"


def test_backend_selection():
    dev = Settings("DEV", "db", "url", "INFO", "drop", "data/bronze")
    prod = make_prod_settings()
    assert isinstance(get_artifact_storage(dev), LocalArtifactStorage)
    assert isinstance(
        get_artifact_storage(prod, blob_service_client=FakeBlobServiceClient()),
        BlobArtifactStorage,
    )


def test_local_backend_preserves_paths_and_contents(tmp_path):
    storage = LocalArtifactStorage(str(tmp_path / "bronze"))
    data = b'"A","B"\n"1","2"\n'
    path, sha, written = storage.write_landing(data)
    assert written is True
    assert path == os.path.join(storage.bronze_dir, "landing", sha + ".csv")
    assert os.path.exists(path)
    path2, sha2, written2 = storage.write_landing(data)
    assert written2 is False
    assert path2 == path and sha2 == sha
    raw = storage.write_run_raw_copy(data)
    assert raw.startswith(os.path.join(storage.bronze_dir, "raw", "yi5j-5fe9_"))
    assert raw.endswith(".csv")
    df = storage.read_landing_csv(sha)
    assert list(df.columns) == ["A", "B"]
    assert df.iloc[0].to_dict() == {"A": "1", "B": "2"}
    storage.export_gold_csvs(str(tmp_path / "gold"), [{"rank": 1}], [], [], [])
    assert os.path.exists(os.path.join(tmp_path, "gold", GOLD_TOP5))


def test_blob_backend_writes_reads_and_dedupes():
    service = FakeBlobServiceClient()
    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    data = b'"FECHA HECHO","COD_DEPTO","DEPARTAMENTO","COD_MUNI","MUNICIPIO","ZONA","CANTIDAD"\n"01/01/2020","05","ANTIOQUIA","05001","MEDELLIN","URBANA","1"\n'
    loc, sha, written = storage.write_landing(data)
    assert loc == "landing/{0}.csv".format(sha)
    assert written is True
    loc2, sha2, written2 = storage.write_landing(data)
    assert (loc2, sha2, written2) == (loc, sha, False)
    raw = storage.write_run_raw_copy(data)
    assert raw.startswith("raw/yi5j-5fe9_") and raw.endswith(".csv")
    assert raw in service.store["bronze-container"]
    df = storage.read_landing_csv(sha)
    assert df.iloc[0]["COD_DEPTO"] == "05"
    assert df.iloc[0]["CANTIDAD"] == "1"


def test_blob_backend_gold_exports_to_gold_container_root():
    service = FakeBlobServiceClient()
    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    storage.export_gold_csvs(
        "ignored/local/path",
        [{"rank": 1, "cod_depto": "05", "departamento": "ANTIOQUIA", "total_crimes": 2}],
        [{"cod_depto": "05", "departamento": "ANTIOQUIA", "total_crimes": 2}],
        [{"year": 2020, "quarter": 1, "month": 1, "weekday_num": 3, "weekday_name": "Wednesday", "total_crimes": 2}],
        [{"electoral_period": "intermediate", "period_order": 2, "year_min": 2020, "year_max": 2020, "total_crimes": 2, "pct_of_total": 100.0}],
    )
    assert set(service.store["gold-container"].keys()) == {GOLD_TOP5, GOLD_DEPT, GOLD_CAL, GOLD_PERIOD}
    assert "ignored" not in "".join(service.store.keys())


def test_ingest_bronze_in_blob_mode(sqlite_engine, sample_csv):
    service = FakeBlobServiceClient()
    settings = make_prod_settings()
    # monkeypatch storage factory by passing storage via monkeypatching get_artifact_storage is easier
    # but ingest_bronze calls get_artifact_storage(settings) directly. Patch it.
    import violence_etl.transformations.bronze as bronze_mod

    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    original = bronze_mod.get_artifact_storage
    bronze_mod.get_artifact_storage = lambda s: storage
    try:
        result = ingest_bronze(sqlite_engine, settings, csv_path=sample_csv)
    finally:
        bronze_mod.get_artifact_storage = original

    sha = result["source_sha256"]
    assert result["status"] == "loaded"
    assert result["source_file"].startswith("raw/yi5j-5fe9_")
    assert "landing/{0}.csv".format(sha) in service.store["bronze-container"]
    # read from blob produced same ingestion count
    assert result["raw_rows"] == 40


def test_build_gold_exports_to_blob(sqlite_engine, settings_sqlite, sample_csv):
    # build local silver data first
    ingest_bronze(sqlite_engine, settings_sqlite, csv_path=sample_csv)
    from violence_etl.transformations.silver import build_silver
    build_silver(sqlite_engine, settings_sqlite)

    service = FakeBlobServiceClient()
    prod = make_prod_settings()
    import violence_etl.transformations.gold as gold_mod

    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    original = gold_mod.get_artifact_storage
    gold_mod.get_artifact_storage = lambda s: storage
    try:
        result = build_gold(sqlite_engine, export_csv=True, export_dir="data/gold", settings=prod)
    finally:
        gold_mod.get_artifact_storage = original

    assert result["grand_total"] == 40
    assert set(service.store["gold-container"].keys()) == {GOLD_TOP5, GOLD_DEPT, GOLD_CAL, GOLD_PERIOD}


def test_ingest_bronze_blob_mode_with_local_csv_path_override(sqlite_engine, sample_csv):
    service = FakeBlobServiceClient()
    settings = make_prod_settings()
    import violence_etl.transformations.bronze as bronze_mod

    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    original = bronze_mod.get_artifact_storage
    bronze_mod.get_artifact_storage = lambda s: storage
    try:
        result = ingest_bronze(sqlite_engine, settings, csv_path=sample_csv)
    finally:
        bronze_mod.get_artifact_storage = original

    with open(sample_csv, "rb") as fh:
        local_bytes = fh.read()
    sha = etl_io.sha256_bytes(local_bytes)

    assert result["status"] == "loaded"
    assert result["source_sha256"] == sha
    assert result["row_count"] == 40
    assert result["raw_rows"] == 40

    landing_blob = "landing/{0}.csv".format(sha)
    assert result["source_file"].startswith("raw/yi5j-5fe9_")
    assert result["source_file"].endswith(".csv")
    assert re.match(r"^raw/yi5j-5fe9_\d{8}T\d{6}Z\.csv$", result["source_file"])
    assert not os.path.isabs(result["source_file"])
    assert sample_csv not in result["source_file"]

    assert set(service.store["bronze-container"].keys()) == {landing_blob, result["source_file"]}
    assert service.store["bronze-container"][landing_blob] == local_bytes
    assert service.store["bronze-container"][result["source_file"]] == local_bytes

    landing_df = storage.read_landing_csv(sha)
    assert len(landing_df) == 40
    assert list(landing_df.columns) == [
        "FECHA HECHO",
        "COD_DEPTO",
        "DEPARTAMENTO",
        "COD_MUNI",
        "MUNICIPIO",
        "ZONA",
        "CANTIDAD",
    ]
    assert landing_df.iloc[0]["COD_DEPTO"] == "05"
    assert landing_df.iloc[0]["CANTIDAD"] == "1"


def test_download_command_reports_blob_location(monkeypatch, capsys):
    from violence_etl import cli

    service = FakeBlobServiceClient()
    storage = BlobArtifactStorage(make_blob_config(), blob_service_client=service)
    prod = make_prod_settings()
    monkeypatch.setattr(cli, "get_settings", lambda: prod)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "get_artifact_storage", lambda s: storage)
    monkeypatch.setattr(etl_io, "download_source", lambda url: b"col1,col2\n1,2\n")

    rc = cli.main(["download"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "landing/" in out
    assert "new=True" in out
