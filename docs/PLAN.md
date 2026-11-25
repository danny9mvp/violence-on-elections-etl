# Implementation Plan: Violence on Elections ETL (Medallion)

This is the design and rationale document. For install, configuration, the CLI
reference, the table catalogue and day-to-day usage, see `README.md`.

## Context and verified source facts

Source: `http://www.datos.gov.co/api/v3/views/yi5j-5fe9/export.csv` (Socrata export, follows a 301 redirect; must use `requests` with `allow_redirects=True` or curl `-L`).

Facts confirmed by direct inspection of the downloaded file during planning. Row, duplicate, and total counts are snapshot dependent and reflect the latest validated run (local DEV, Docker, 2026-11-20) unless noted; file size, date range, zone distribution, and department/municipality counts below are from the planning inspection and were not re-derived from that run.

- Plain CSV, comma separated, every field quoted, 976,021 bytes (planning inspection).
- Header exactly: `"FECHA HECHO","COD_DEPTO","DEPARTAMENTO","COD_MUNI","MUNICIPIO","ZONA","CANTIDAD"`.
- 15,981 data rows (latest validated snapshot; 15,696 at planning inspection).
- `FECHA HECHO` is `DD/MM/YYYY`, not ISO.
- `COD_DEPTO` is always 2 chars, `COD_MUNI` is always 5 chars, both zero padded, must stay text.
- `ZONA` values observed during planning: `URBANA` (9,813) and `RURAL` (5,883).
- `CANTIDAD` was always the literal `1` in every row during planning inspection.
- 32 distinct departments, 777 distinct municipality codes (planning inspection).
- Date range min `2003-01-01`, max `2026-08-31` during planning inspection; rows arrive in descending date order.
- 14,460 distinct business rows in silver with `ETL_DEDUP_MODE=drop`; 1,521 rows removed as exact duplicates in the latest validated snapshot (largest duplicate group was 24 copies at planning inspection). Raw rows 15,981, silver rows 14,460, rejected 0, `total_crimes` 15,981, `gold_grand_total` 15,981.
- No empty cells in the planning sample. Nulls and unparseable dates are still validated by design.

## Target runtime and dependency strategy (Python 3.8 to 3.14)

The stack must import and run on both Python 3.8 and Python 3.14 from one source tree. Code rules:

- Add `from __future__ import annotations` at the top of every module that uses annotations.
- Never use `match`, PEP 604 `X | Y`, builtin generics (`list[str]`, `dict[str, int]`) in runtime-evaluated positions, `dict |` union operators, or removed stdlib APIs (`distutils`, `imp`, `asyncio.coroutine`, positional `collections.namedtuple` defaults, etc.).
- Use `typing.List`, `typing.Optional`, `typing.Dict`, `typing.Tuple` in signatures.
- Use SQLAlchemy classic `Column(...)` declarative style, not `Mapped[...]` / `mapped_column`, to avoid runtime annotation evaluation differences across 3.8 and 3.14.
- `datetime.UTC` does not exist on 3.8; use `datetime.timezone.utc`. `datetime.date.fromisocalendar` exists since 3.8 (ok). `zoneinfo` is 3.9+; avoid it.

One dependency cannot span 3.8 to 3.14 with a single pin: pandas (and its numpy build). pandas 2.0.3 is the last release that installs on 3.8 but it has no CPython 3.13 or 3.14 wheels; pandas 2.3.3 has 3.9 to 3.14 wheels (including cp314) but requires >=3.9. Fix: environment markers in `requirements.txt`. The same marker pattern is used for numpy and, in `requirements-dev.txt`, for pytest-cov, coverage and the Jupyter dev stack. pytest, python-dotenv and requests use a single pin because one release spans the whole range, and psycopg2-binary is avoided entirely. PostgreSQL driver uses psycopg 3 (`psycopg==3.2.10` with `psycopg-binary==3.2.10`, which has cp38 through cp314 wheels), dialect URL `postgresql+psycopg://`.

For production (`ENV=PROD`), PostgreSQL credentials and blob storage
configuration are fetched from Azure Key Vault (`AZURE_KEYVAULT_URL`) using
`DefaultAzureCredential`. Database secrets are `PGHOST`, `PGPORT`, `PGUSER`,
`PGPASSWORD`, and `PGDATABASE`; blob storage secrets are `STORAGEACCOUNT`,
`BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER`. The PostgreSQL
connection uses `sslmode=require`. Bronze and gold CSV artifacts are stored in
Azure Blob Storage containers in `PROD` (landing/raw in `BRZECONTAINER`, gold
exports in the `GOLDCONTAINER` root). `SILVCONTAINER` is configured now as a
reserved location for future silver CSV artifacts. `get_settings()` eagerly
fetches and validates blob storage configuration in `PROD` so missing or
invalid values fail fast at startup. Runtime dependencies include
`azure-identity`, `azure-keyvault-secrets`, and `azure-storage-blob`; Azure SDK
imports are lazy so local development and automated tests use SQLite and local
`data/` artifacts (`ENV=DEV|TEST`) without requiring Azure packages at runtime.

## Containerized execution model

A runtime-only Docker image (`python:3.12.12-slim`, pinned) packages `src/`,
`migrations/`, `alembic.ini`, and `requirements.txt`, sets `PYTHONPATH=/app/src`
and `PYTHONUNBUFFERED=1`, runs as a non-root user, and defaults to
`python -m violence_etl.cli init-db && python -m violence_etl.cli run-all`.
Command overrides replace the whole chain, so maintenance commands must include
`init-db` explicitly when needed.

For local DEV (`docker-compose.yml`, `ENV=DEV`), SQLite and local bronze/gold
artifacts persist via a mounted data path under `/app/data` (default
`./data:/app/data`). Linux bind mounts may require host ownership alignment,
configurable UID/GID mapping, or a named volume. Local `data/` persistence is a
DEV/TEST concern.

For PROD, the same image is intended to run as a monthly run-to-completion
Azure Container Apps Job with `ENV=PROD` and `AZURE_KEYVAULT_URL`, using
`DefaultAzureCredential`/managed identity with existing Key Vault, PostgreSQL,
and Blob Storage integrations. No data volume is required or expected in PROD;
missing required configuration/secrets, auth failures, or unreachable
dependencies should fail fast and surface as job failure. See `README.md` for
build/run examples and override behavior.

## requirements.txt (runtime, pinned, with markers)

```
# Core
SQLAlchemy==2.0.44
alembic==1.14.1

# PostgreSQL driver (psycopg 3, cp38..cp314 wheels)
psycopg==3.2.10
psycopg-binary==3.2.10

# Data manipulation, split by interpreter range because no single pin spans 3.8..3.14
numpy==1.24.4; python_version < "3.9"
pandas==2.0.3; python_version < "3.9"
numpy==2.0.2; python_version >= "3.9" and python_version < "3.11"
pandas==2.3.3; python_version >= "3.9"
numpy==2.3.2; python_version >= "3.11"

# HTTP, config, utils
requests==2.31.0
python-dotenv==1.0.1

# Azure Key Vault (PostgreSQL credentials in PROD)
azure-identity==1.17.1
azure-keyvault-secrets==4.8.0

# Azure Blob Storage (artifact storage in PROD)
azure-storage-blob==12.22.0
```

Notes:
- SQLAlchemy 2.0.44 declares `>=3.7` and ships cp38..cp313 wheels plus a `py3-none-any` fallback, so it installs on 3.14 via the pure-Python wheel.
- alembic 1.14.1 declares `>=3.8` and is pure Python (`py3-none-any`), so it spans the whole range. Do not use alembic >=1.16 (requires >=3.9).
- pytest is deliberately excluded from runtime requirements and lives in the dev file.

## requirements-dev.txt

```
-r requirements.txt
pytest==8.3.5
ruff==0.8.6
pytest-cov==5.0.0; python_version < "3.9"
pytest-cov==6.2.1; python_version >= "3.9"
coverage==7.6.1; python_version < "3.9"
coverage==7.10.6; python_version >= "3.9"

# Exploratory notebooks (PyCharm managed Jupyter server)
jupyterlab==4.0.13; python_version < "3.9"
jupyterlab==4.4.9; python_version >= "3.9"
notebook==7.0.7; python_version < "3.9"
notebook==7.4.7; python_version >= "3.9"
ipykernel==6.29.5; python_version < "3.9"
ipykernel==6.30.1; python_version >= "3.9"
```

A `requirements-dev.txt` is warranted: tests, coverage, and the notebook runtime are needed for development and CI but not to run the pipeline, and the notebook stack is heavy and must not leak into the production image.

Install commands:

```
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

## Repository layout

The application package lives under `src/violence_etl/` (`src/` layout). Run the
CLI from the repository root with `PYTHONPATH=src` (or install the project in
editable mode) so `python -m violence_etl.cli ...` resolves the package.

```
ViolenceOnElectionsEtl/
├── .gitignore
├── .env.example
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml                 # pytest/ruff config
├── alembic.ini
├── Makefile                       # thin task aliases
├── docs/
│   └── PLAN.md
├── migrations/                    # alembic root (at repo root)
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_bronze.py
│       ├── 0002_silver.py
│       ├── 0003_gold.py
│       └── 0004_bronze_ingestion_unique.py
├── src/
│   └── violence_etl/
│       ├── __init__.py
│       ├── cli.py                 # argparse entry point
│       ├── pipeline.py            # orchestration (run_bronze/silver/gold/run_all)
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── key_vault.py       # generic KeyVaultClient secret reader
│       │   └── object_storage.py  # low-level object storage client
│       ├── config/
│       │   ├── __init__.py        # REPO_ROOT (repo root)
│       │   ├── settings.py        # env-driven config
│       │   └── logging_conf.py
│       ├── db/
│       │   ├── __init__.py        # REPO_ROOT
│       │   ├── connection.py      # engine + session factory
│       │   └── models/
│       │       ├── __init__.py    # REPO_ROOT
│       │       ├── base_model.py  # SQLAlchemy Base
│       │       ├── bronze_*.py
│       │       ├── silver_*.py
│       │       └── gold_*.py
│       ├── exceptions/
│       │   ├── __init__.py        # REPO_ROOT
│       │   └── *.py               # typed exceptions
│       ├── storage/
│       │   ├── __init__.py        # package marker
│       │   ├── blob_storage.py    # blob artifact storage service (PROD)
│       │   ├── factory.py         # artifact storage factory
│       │   └── local_storage.py   # local artifact storage service (DEV/TEST)
│       ├── transformations/
│       │   ├── __init__.py        # REPO_ROOT
│       │   ├── bronze.py
│       │   ├── silver.py
│       │   └── gold.py
│       └── utils/
│           ├── __init__.py        # REPO_ROOT
│           ├── io.py
│           ├── schema.py
│           ├── periods.py
│           └── timeutil.py
├── data/
│   ├── bronze/
│   │   ├── landing/.gitkeep
│   │   └── raw/.gitkeep
│   ├── silver/.gitkeep
│   ├── gold/.gitkeep
│   └── warehouse/.gitkeep         # sqlite db files (gitignored)
├── notebooks/
│   ├── README.md
│   ├── 01_bronze_profiling.ipynb
│   ├── 02_silver_validation.ipynb
│   └── 03_gold_analysis.ipynb
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── test_bronze.py
    ├── test_gold.py
    ├── test_periods.py
    ├── test_pipeline_sqlite.py
    ├── test_schema.py
    ├── test_settings.py
    └── test_silver.py
```

Where things live:
- Raw landing originals: `data/bronze/landing/<sha256>.csv` (verbatim bytes, never edited).
- Raw table mirror: `bronze_crimes_raw` in the warehouse DB, all source fields stored as text.
- Curated table: `silver_crimes`.
- Rejected rows: `silver_rejected_rows`.
- Denormalized query objects: `gold_*` tables.
- Code: `src/violence_etl/` (package modules under `clients/`, `config/`, `db/`, `db/models/`, `exceptions/`, `transformations/`, `utils/`).
- Migrations: `migrations/` (repo root), with `alembic.ini` at the repo root.
- Tests: `tests/`.
- Notebooks: `notebooks/`.
- Config: `src/violence_etl/config/` plus `.env`. `REPO_ROOT` in `src/violence_etl/cli.py` and package `__init__` modules resolves to the repository root so the CLI finds `alembic.ini` and `migrations/`.

One codebase, two databases: use table-name prefixes (`bronze_`, `silver_`, `gold_crimes_by_electoral_period.py`) rather than PostgreSQL schemas, because SQLite has no schemas. This keeps a single set of SQLAlchemy models and one Alembic history working identically on SQLite (staging/tests) and PostgreSQL (warehouse).

## Settings module (single env-driven config)

`src/violence_etl` exposes frozen `Settings` and `BlobStorageConfig`
dataclasses, a `get_settings()` factory, and URL/config helpers. The full
variable table is in `README.md`; this section records the design intent.

```python
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
class BlobStorageConfig:
    storage_account_name: str
    bronze_container: str
    silver_container: str
    gold_container: str

@dataclass(frozen=True)
class Settings:
    env: str              # "DEV" | "TEST" | "PROD"
    sqlite_path: str
    source_url: str
    log_level: str
    dedup_mode: str       # "drop" | "sum"
    bronze_dir: str
    key_vault_url: Optional[str] = field(default=None, repr=False)
    blob_storage: Optional[BlobStorageConfig] = None

    @property
    def is_sqlite(self) -> bool:
        return self.env in ("DEV", "TEST")
```

Design points:

- `ENV` selects the runtime target. `DEV` and `TEST` use SQLite at
  `ETL_SQLITE_PATH` and local `data/` artifact paths. `PROD` uses Azure
  PostgreSQL and Azure Blob Storage for bronze/gold CSV artifacts.
- PostgreSQL credentials are not read from local environment variables and there
  is no `DATABASE_URL` override. In `PROD`, `AZURE_KEYVAULT_URL` is required.
  `get_settings()` eagerly fetches and validates blob storage configuration
  from Key Vault using `DefaultAzureCredential` (secrets `STORAGEACCOUNT`,
  `BRZECONTAINER`, `SILVCONTAINER`, `GOLDCONTAINER`) so missing or invalid
  values fail fast at startup. Database secrets (`PGHOST`, `PGPORT`, `PGUSER`,
  `PGPASSWORD`, `PGDATABASE`) are resolved from Key Vault when building the
  PostgreSQL URL.
- Generic secret reads use `KeyVaultClient` in
  `src/violence_etl/clients/key_vault.py`. It works for any secret, accepts an
  injected credential or secret client, and imports the Azure SDK lazily, so
  `DEV`/`TEST` and injected-client tests need no Azure packages.
- `postgres_url_from_key_vault(vault_url)` in `settings.py` owns the PostgreSQL
  secret names, parses `PGPORT` with `int()`, and builds the
  `postgresql+psycopg://` URL with `sslmode=require`. `database_url_object()`
  returns a SQLite URL for `DEV`/`TEST` and calls this helper for `PROD`.
  `blob_storage_config_from_key_vault(vault_url, credential=None, client=None)`
  resolves `BlobStorageConfig` from the four blob secrets via `KeyVaultClient`.
  `database_url_display()` masks the password for logging.
- `get_artifact_storage(settings)` in `src/violence_etl/storage/factory.py`
  returns `LocalArtifactStorage` for `DEV`/`TEST` and `BlobArtifactStorage` for
  `PROD`. Low-level object storage access lives in
  `src/violence_etl/clients/object_storage.py`; storage services use that client
  and keep Azure SDK usage out of `storage/__init__.py`.
- The CLI global flags `--sqlite-path` and `--log-level` are pushed into the
  environment before `get_settings()` is called, so the rest of the code path is
  unchanged.

`.env.example` contains the keys with their defaults; `.env` is gitignored.

## Bronze layer

Goal: preserve the source verbatim and mirror it exactly, plus ingestion metadata.

Artifacts:
1. Landing artifact: exact downloaded bytes named by content hash. In
   `DEV`/`TEST` this is `data/bronze/landing/<sha256>.csv`; in `PROD` this is
   `landing/<sha256>.csv` in `BRZECONTAINER`.
2. Run-stamped raw copy: `raw/yi5j-5fe9_<utcstamp>.csv`, stored under the local
   bronze directory in `DEV`/`TEST` or in `BRZECONTAINER` in `PROD`.
3. Raw table `bronze_crimes_raw`: every source column stored as text, plus
   metadata columns.
4. Ingestion log `bronze_ingestion_log`: one row per source content hash,
   updated in place on every attempt (`loaded` or `skipped`), so repeated runs
   are idempotent. See README "Idempotency and reload semantics".

In `PROD`, reported bronze artifact identifiers (`source_file`, download landing
location) are blob names within the bronze container. When `csv_path` is
provided, its bytes are read locally but resulting bronze artifacts are written
to the active backend.

## Table definitions (SQLAlchemy classic column style, `src/violence_etl`)

```python
Base = declarative_base()

class BronzeCrimesRaw(Base):
    __tablename__ = "bronze_crimes_raw"
    __table_args__ = (
        UniqueConstraint("source_sha256", "row_num", name="uq_bronze_source_row"),
    )
    raw_id = Column(Integer, primary_key=True, autoincrement=True)
    source_sha256 = Column(String(64), nullable=False, index=True)
    source_file = Column(String(255), nullable=False)
    source_url = Column(String(512), nullable=False)
    load_ts = Column(DateTime(timezone=False), nullable=False)
    row_num = Column(Integer, nullable=False)          # 1-based data row order
    fecha_hecho_raw = Column(Text, nullable=True)       # verbatim "FECHA HECHO"
    cod_depto_raw = Column(Text, nullable=True)
    departamento_raw = Column(Text, nullable=True)
    cod_muni_raw = Column(Text, nullable=True)
    municipio_raw = Column(Text, nullable=True)
    zona_raw = Column(Text, nullable=True)
    cantidad_raw = Column(Text, nullable=True)

class BronzeIngestionLog(Base):
    __tablename__ = "bronze_ingestion_log"
    ingestion_id = Column(Integer, primary_key=True, autoincrement=True)
    source_url = Column(String(512), nullable=False)
    source_file = Column(String(255), nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    row_count = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)         # "loaded" | "skipped" | "failed"
    message = Column(Text, nullable=True)
    loaded_at = Column(DateTime(timezone=False), nullable=False)
```

`String(64)`, `String(255)`, `Text` are used (not `String` without length) so the schema renders identically on SQLite and PostgreSQL.

## Bronze ingestion behavior (`src/violence_etl`)

Artifact persistence is abstracted by environment: `DEV`/`TEST` use
`LocalArtifactStorage` rooted at `ETL_BRONZE_DIR`, while `PROD` uses
`BlobArtifactStorage` (`src/violence_etl/storage/blob_storage.py`) with
low-level object storage access provided by `ObjectStorageClient`
(`src/violence_etl/clients/object_storage.py`). In `PROD`, bronze landing/raw
artifacts are blob names in `BRZECONTAINER` (`landing/<sha256>.csv`,
`raw/yi5j-5fe9_<utcstamp>.csv`) and are stored/reported as those identifiers.

Function `ingest_bronze(engine, settings, csv_path=None) -> dict`:

1. If `csv_path` is None, download `settings.source_url` with `requests.get(..., allow_redirects=True, stream=True, timeout=120)` into memory, compute sha256, write the landing artifact if absent, and write the run-stamped raw copy via the active storage backend.
2. Read the CSV with `pandas.read_csv(path, dtype=str, keep_default_na=False, quoting=csv.QUOTE_ALL)` so all fields stay text and empty strings stay empty strings (no NaN coercion).
3. Assert the header equals the 7 expected names in order from `src/violence_etl`; raise `SchemaError` on mismatch (fail fast, no partial load).
4. Idempotency: if `bronze_crimes_raw` already holds rows for this `source_sha256` and `--force` is not set, update the log row for that hash to `status="skipped"` and return `{"status": "skipped", ...}` without inserting raw rows.
5. Otherwise delete any existing `bronze_crimes_raw` rows for this `source_sha256`, then bulk insert with the metadata columns. `load_ts` is `datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)` (naive UTC, works on 3.8 and 3.14).
6. Upsert the `bronze_ingestion_log` row for this hash (`UNIQUE(source_sha256)`) with `status="loaded"` and the row count, in one transaction.

No cleaning happens here. Text stays text.

## Silver layer

Goal: typed, trimmed, uppercased, code-preserving, deduplicated, validated, calendar-enriched rows.

## Cleaning rules (enumerated, applied in this order)

R1. Strip leading/trailing whitespace on every text field (`str.strip()`).
R2. Uppercase `departamento`, `municipio`, `zona` (`str.upper()`). Applied with `.str.upper()` after whitespace strip.
R3. `cod_depto` and `cod_muni`: keep as zero-padded strings. Enforce exactly 2 and 5 characters via `str.zfill(2)` / `str.zfill(5)`; if the raw value is non numeric, reject the row (R10).
R4. `fecha_hecho`: parse with explicit format `%d/%m/%Y` via `pandas.to_datetime(..., format="%d/%m/%Y", errors="coerce")`. Never let pandas infer (avoids `MM/DD` ambiguity). Unparseable becomes `NaT` and is rejected by R10.
R5. `cantidad`: cast to integer. Since verified all values are `1`, cast via `pandas.to_numeric(..., errors="coerce").astype("Int64")` then to int on load; non numeric or negative becomes `NaN` and is rejected.
R6. `zona`: keep only `URBANA` / `RURAL`; anything else is rejected (R10).
R7. Null check on `fecha_hecho`, `cod_depto`, `departamento`, `cod_muni`, `municipio`, `zona`, `cantidad`. Any null is rejected (R10). Empty string counts as null.
R8. Referential sanity: `cod_depto` must equal the first 2 characters of `cod_muni`; if not, reject with reason `depto_muni_mismatch`.
R9. Deduplication. Chosen rule, deliberate: drop exact duplicate business rows, keeping the first occurrence, keyed on `(fecha_hecho, cod_depto, cod_muni, zona, cantidad)`. `departamento` and `municipio` are functionally dependent on the codes, so they are not part of the key. Configurable via `ETL_DEDUP_MODE`:
    - `drop` (default): keep one row per key. Effect on the latest validated snapshot (local DEV, Docker, 2026-11-20): 15,981 raw rows to 14,460 silver rows, removing 1,521 exact duplicates (9.52 percent), with `rejected=0`, `total_crimes=15981`, and `gold_grand_total=15981`. Snapshot counts can change as the source updates.
    - `sum`: group by the key without `cantidad` and sum `CANTIDAD`. Provided for datasets where `CANTIDAD` is a real magnitude and duplicate rows are partial reports. Row and total counts under `sum` depend on the source snapshot; verify by running with `ETL_DEDUP_MODE=sum`.
    The default `drop` treats repeated identical rows as ingestion duplication, not distinct events, because the source has no event id. At planning inspection `CANTIDAD` was always `1`.
R10. Every rejected row is copied (raw values plus a `reject_reason`) to `silver_rejected_rows` in the same transaction, so nothing is silently lost.
R11. Calendar derivation from `fecha_hecho`: `year`, `month` (1-12), `quarter` (1-4 from `(month-1)//3+1`), `weekday_num` (ISO 1=Monday .. 7=Sunday via `dt.weekday()+1`), `weekday_name` (`Monday`..`Sunday`).
R12. Electoral period assignment via `src/violence_etl` (next section).
R13. Add `row_hash` = sha256 hex of the dedup key fields, for audit and idempotency, plus `silver_loaded_at`.

## Silver table definition

```python
class SilverCrimes(Base):
    __tablename__ = "silver_crimes"
    __table_args__ = (
        UniqueConstraint("fecha_hecho", "cod_depto", "cod_muni", "zona",
                         "cantidad", name="uq_silver_business_key"),
        Index("ix_silver_year_period", "year", "electoral_period"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha_hecho = Column(Date, nullable=False, index=True)
    cod_depto = Column(String(2), nullable=False)
    departamento = Column(String(100), nullable=False)
    cod_muni = Column(String(5), nullable=False)
    municipio = Column(String(150), nullable=False)
    zona = Column(String(10), nullable=False)
    cantidad = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    weekday_num = Column(Integer, nullable=False)
    weekday_name = Column(String(10), nullable=False)
    electoral_period = Column(String(20), nullable=False, index=True)
    row_hash = Column(String(64), nullable=False)
    source_sha256 = Column(String(64), nullable=False, index=True)
    silver_loaded_at = Column(DateTime(timezone=False), nullable=False)

class SilverRejectedRows(Base):
    __tablename__ = "silver_rejected_rows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_sha256 = Column(String(64), nullable=True)
    row_num = Column(Integer, nullable=True)
    reject_reason = Column(String(64), nullable=False)
    raw_values = Column(Text, nullable=False)          # JSON string of raw dict
    rejected_at = Column(DateTime(timezone=False), nullable=False)
```

`String(100)` / `String(150)` cover the observed maxima (18 and 27 chars) with headroom.

## Silver load behavior (`src/violence_etl`)

Function `build_silver(engine, settings, sha=None, force=False) -> dict`:

1. Read `bronze_crimes_raw` for the target `source_sha256` (default: `latest_loaded_sha`, the snapshot with the highest `raw_id`, derived from the raw rows rather than the ingestion-log status) into a DataFrame via `pandas.read_sql`.
2. Apply R1..R8, splitting valid and rejected frames.
3. Apply R9 dedup per `settings.dedup_mode`.
4. Apply R11..R13.
5. Idempotency: full deterministic refresh. Silver keeps a single active snapshot: rows for any other `source_sha256` are purged first, so an updated export replaces the previous one and gold never mixes snapshots. If `force`, rows for this sha are deleted first; then rows are inserted with business-key conflicts ignored (`ON CONFLICT DO NOTHING` on PostgreSQL, `INSERT OR IGNORE` on SQLite), so a second identical run writes zero new rows. `inserted_rows` is the insert rowcount; `silver_rows`/`total_crimes` are read back from the database.
6. Rebuild rejected rows for this sha.
7. Return counts: `{"raw_rows", "silver_rows", "inserted_rows", "rejected_rows", "dropped_duplicates", "total_crimes", "dedup_mode"}` and log them.

## Electoral period classification

Values (exactly): `pre-electoral`, `electoral`, `intermediate`, `post-electoral`.

Definitions:
- electoral: the election year.
- pre-electoral: 1 year before the election year.
- post-electoral: 1 year after the election year.
- intermediate: the single year between post-electoral and the next pre-electoral.

Reference cycle from the brief, which the rule must reproduce exactly: `pre-electoral: 2013, electoral: 2014, post-electoral: 2015, intermediate: 2016, pre-electoral: 2017`.

## Authoritative rule (configurable)

Colombian general elections (presidencia and congreso) are every 4 years: 2002, 2006, 2010, 2014, 2018, 2022, 2026.

`src/violence_etl`:

```python
from __future__ import annotations
from typing import Dict, Iterable, Tuple

ELECTION_YEARS: Tuple[int, ...] = (2002, 2006, 2010, 2014, 2018, 2022, 2026)
CYCLE_ANCHOR = ELECTION_YEARS[0]
CYCLE_LEN = 4
UNCLASSIFIED = "unclassified"

_OFFSET_TO_PERIOD: Dict[int, str] = {
    0: "electoral",
    1: "post-electoral",
    2: "intermediate",
    3: "pre-electoral",
}

def is_cycle_valid(election_years: Iterable[int] = ELECTION_YEARS) -> bool:
    ys = sorted(election_years)
    return all((b - a) == CYCLE_LEN for a, b in zip(ys, ys[1:]))

def electoral_period(year, election_years=ELECTION_YEARS) -> str:
    if year < CYCLE_ANCHOR - 1:
        return UNCLASSIFIED
    if year in set(election_years):
        return "electoral"
    if (year - 1) in set(election_years):
        return "post-electoral"
    if (year + 1) in set(election_years):
        return "pre-electoral"
    offset = (year - CYCLE_ANCHOR) % CYCLE_LEN
    return _OFFSET_TO_PERIOD[offset]
```

The function first does explicit membership tests (semantic anchors), then falls back to modular arithmetic. `is_cycle_valid` is asserted at import/log time; if a customized `ELECTION_YEARS` is not exactly 4 years apart the module logs a warning.

Out-of-cycle years: any year strictly before `CYCLE_ANCHOR - 1` (that is, before 2001) returns `unclassified`. With the default configuration every year from 2001 onward maps, so every year in the dataset (2003..2026) is classified and no year is unmapped.

## Complete mapping table 2003..2026

The full 2003..2026 table lives in `README.md` and is asserted year by year in
`tests/test_periods.py`, so the mapper cannot silently drift. It covers the
whole data range with no unmapped year.

## Gold layer

Goal: small denormalized tables ready for direct SQL or BI queries. Built by full refresh (truncate and rewrite) from `silver_crimes`, which keeps them deterministic and idempotent. Tables, not views, so the same objects work on SQLite and PostgreSQL.

The four tables and their columns are catalogued in `README.md`; the models live in `src/violence_etl`.

Object mapping to the requirement:
- a. top 5 departments by total crimes -> `gold_top5_departments` (`rank` 1..5, ordered by `total_crimes DESC`, tie-break `departamento ASC`).
- b. total crimes by department -> `gold_crimes_by_department` (all 32 departments).
- c. total crimes by year, month, weekday and quarter -> `gold_crimes_by_calendar` (grain: year x quarter x month x weekday).
- d. total crimes by electoral period -> `gold_crimes_by_electoral_period` (`period_order` uses post, intermediate, pre, electoral for stable presentation or calendar order, documented in README; `pct_of_total` is share of the grand total, rounded to 2 decimals).

`src/violence_etl` exposes `build_gold(engine, export_csv=False, export_dir="data/gold", settings=None) -> dict`, which for each table: `DELETE` existing rows, run the aggregation with `pandas.groupby` or an `INSERT ... SELECT`, commit, and return row counts plus the grand total. Optionally exports the four gold CSVs via the artifact storage backend: in `DEV`/`TEST` to local `export_dir`, in `PROD` to the `GOLDCONTAINER` root regardless of `export_dir`.

Optional convenience: Alembic creates the four `gold_*` tables; the pipeline fills them. No gold views are required, but `README.md` documents the equivalent `SELECT` for each.

## Migrations (Alembic)

Setup:

```
alembic init -t generic migrations
```

`alembic.ini`: leave `sqlalchemy.url` blank; `env.py` sets it from settings so the same migrations run on SQLite and PostgreSQL.

`migrations/env.py` key points:

```python
from violence_etl.config.settings import get_settings, database_url
from violence_etl import Base

config.set_main_option("sqlalchemy.url", database_url(get_settings()))
target_metadata = Base.metadata


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()
```

Revision sequence (write migrations by hand, not autogenerate, so type choices are explicit and identical on both engines):

```
alembic revision -m "bronze tables"
alembic revision -m "silver tables"
alembic revision -m "gold tables"
alembic upgrade head
alembic downgrade base
alembic current
alembic history
```

- `0001_bronze.py`: create `bronze_crimes_raw`, `bronze_ingestion_log`, and indexes.
- `0002_silver.py`: create `silver_crimes`, `silver_rejected_rows`, unique constraint and indexes.
- `0003_gold.py`: create the four `gold_*` tables.
- `0004_bronze_ingestion_unique.py`: collapse legacy duplicate ingestion-log rows
  and add `UNIQUE(source_sha256)`.

Each migration has a working `downgrade`.

## CLI

`src/violence_etl` uses `argparse` (stdlib, identical on 3.8/3.14). Entry point (from the repository root): `PYTHONPATH=src python -m violence_etl.cli <command>`.

The command list, the per-command flags and the `Makefile` aliases are in `README.md`. Design note: the global flags (`--sqlite-path`, `--log-level`) are pushed into the environment before `get_settings()` is called, so the rest of the code path is unchanged. Runtime target selection is controlled by `ENV` (`DEV|TEST|PROD`) and, for `PROD`, `AZURE_KEYVAULT_URL`.

## Logging

`src/violence_etl`:

```python
def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
```

Every layer logs: start, input row count, output row count, dropped/rejected counts, total crimes, elapsed seconds, and the `source_sha256`. Errors log the exception with `exc_info=True` and re-raise as a typed error.

## Idempotency and error handling

- Bronze: content-hash keyed. Re-downloading identical bytes is a no-op; `bronze_crimes_raw` has `UNIQUE(source_sha256, row_num)` and re-ingestion does delete-then-insert for that sha. `--force` bypasses the skip.
- Silver: `UNIQUE(fecha_hecho, cod_depto, cod_muni, zona, cantidad)`; inserts use `ON CONFLICT DO NOTHING` (PostgreSQL) / `INSERT OR IGNORE` (SQLite). Re-running inserts zero new rows. `--force` does a full deterministic rebuild.
- Gold: full refresh (`DELETE` then aggregate-insert) inside one transaction. Always converges to the same content.
- Pipeline is safe to run repeatedly end to end; a second `run-all` on the same source changes nothing and logs `skipped` at bronze.
- Error handling: `SchemaError` on header mismatch (fail fast, no writes). Row-level problems never abort the load; they route to `silver_rejected_rows` with a reason. DB errors roll back the transaction for that layer and surface with a non-zero exit code from the CLI.
- Typed exceptions in `src/violence_etl`: `EtlError`, `SchemaError`, `DownloadError`, `LoadError`.

## Test plan

Runner: pytest 8.3.5. Config in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
filterwarnings = ["ignore::DeprecationWarning"]
markers = [
    "full_dataset: runs against the real downloaded dataset when ETL_FULL_DATASET=1",
]
```

Current result on Python 3.14: 102 passed, 1 skipped.

Fixtures in `tests/conftest.py`:
- `clean_etl_env`: autouse, removes the ETL/PG env vars so defaults are deterministic.
- `sqlite_engine`: creates a temp SQLite file under `tmp_path`, runs `Base.metadata.create_all`, yields the engine, disposes after.
- `settings_sqlite`: Settings pointed at the temp SQLite file and a temp bronze dir.
- `sample_csv`: path to `tests/fixtures/yi5j-5fe9_sample.csv` (40 hand-built rows covering both zones, both duplicate and distinct rows, all four period types, edge dates).
- `bad_csv`: path to `tests/fixtures/yi5j-5fe9_bad.csv` (empty date, non numeric code, unexpected `ZONA`, `DD/MM` vs `MM/DD` ambiguity, null municipio).
- `many_depts_csv`: path to `tests/fixtures/yi5j-5fe9_many_depts.csv` (7 departments, for top-5 truncation).

Unit tests:
- `test_periods.py`: the full 2003..2026 table asserted year by year; the reference cycle `{2013: pre-electoral, 2014: electoral, 2015: post-electoral, 2016: intermediate, 2017: pre-electoral}`; `2002 -> electoral`, `2026 -> electoral`, `2001 -> pre-electoral`; `2000 -> unclassified`; a non-4-year `ELECTION_YEARS` triggers `is_cycle_valid` False.
- `test_schema.py`: exact expected header list, order, and case; mismatch raises `SchemaError`.
- `test_settings.py`: defaults to `ENV=DEV` with SQLite; `DEV`/`TEST` build SQLite URLs; invalid `ENV` raises; `ENV=PROD` requires `AZURE_KEYVAULT_URL`; PROD fetches PostgreSQL credentials from Key Vault (monkeypatched at `violence_etl.config.settings.postgres_url_from_key_vault`) and returns a URL with `sslmode=require`; masked display URLs do not leak the password.
- `test_key_vault_client.py`: `KeyVaultClient` reads non-empty secrets from an injected fake client; an injected credential avoids importing `azure.identity`; missing Azure packages raise a clear `ImportError`; empty or missing secret values raise `ValueError`; `postgres_url_from_key_vault()` builds the URL from fake secrets, rejects an empty vault URL and a non-integer `PGPORT`; `DEV`/`TEST` URL building does not import the Key Vault client.
- `test_silver.py`: all R1..R13 rules individually; zero padding preserved on load (assert `cod_depto == "05"`, `cod_muni == "05660"`); date `31/08/2026` parses to `2026-08-31`; `11/12/2024` parses as 11 Dec not 12 Nov; exact-duplicate rows collapse (3 identical -> 1); `dedup_mode="sum"` sums instead; rejected rows land in `silver_rejected_rows` with the expected reason; `inserted_rows` tracks actual writes (second run is 0); a new snapshot purges the previous sha.
- `test_bronze.py`: header validation; `keep_default_na=False` keeps empty strings as empty strings; content hash stable; re-ingest of the same sha skips and updates the single log row; `--force` reloads without growing the log.
- `test_gold.py`: top 5 ordering and rank values on the sample; `gold_crimes_by_department` totals equal the silver total; `gold_crimes_by_calendar` grain uniqueness; `gold_crimes_by_electoral_period` `pct_of_total` sums to about 100; top-5 truncates when more than five departments exist; the period order matches the expected labels; `export_csv=True` writes all four files.

Integration test `test_pipeline_sqlite.py`:
- Uses a real temp SQLite file and the committed `sample_csv` fixture.
- Runs `run_all` once, asserts bronze row count equals the CSV data row count, silver row count equals distinct business rows, `silver_rejected_rows` count matches the expected rejects, and gold tables are populated.
- Runs `run_all` a second time and asserts no row counts change (idempotency), including with rejected rows.
- Asserts the grand total from `gold_crimes_by_department` equals the grand total from `gold_crimes_by_electoral_period` equals the sum of silver `cantidad`.
- Slow marker `@pytest.mark.full_dataset` runs against the real downloaded file when `ETL_FULL_DATASET=1`; skipped by default so CI stays fast and offline.

Exact commands are in `README.md`.

## Notebook plan

Notebooks use the PyCharm IDE managed Jupyter server (Project Settings > Python Interpreter > Jupyter: let PyCharm start/manage the server; the kernel is the project `.venv`). No separate `jupyter notebook` process is required. The notebook stack lives in `requirements-dev.txt`. Commit the `.ipynb` files; `.ipynb_checkpoints/` and `.jupyter/` are gitignored.

- `notebooks/01_bronze_profiling.ipynb`: download or open the landing file, profile the raw CSV (row count, nulls, dtypes, value counts for `ZONA`, duplicate groups, date range), confirm the planning facts, and show the raw table after `ingest-bronze`.
- `notebooks/02_silver_validation.ipynb`: run `build-silver` against SQLite, show before/after row counts, the dedup effect for the latest validated snapshot (15,981 raw rows to 14,460 silver rows, 1,521 duplicates removed, `total_crimes` 15,981), the rejected-rows breakdown, and the electoral-period distribution per year using the mapping table. Counts can change as the source snapshot updates.
- `notebooks/03_gold_analysis.ipynb`: query the four `gold_*` tables, render the top 5 departments, the by-department ranking, the calendar heat-style tables, and the crimes-by-electoral-period share, as a template that the README links to.

Each notebook starts with a bootstrap cell that inserts the repo root on `sys.path` and sets `ENV=DEV` so notebooks use the local SQLite database and never touch PostgreSQL by accident.

## .gitignore

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.pytest_cache/
.coverage
coverage.xml
htmlcov/

# Virtualenv
.venv/
venv/
env/

# PyCharm
.idea/
*.iml
out/

# Env
.env

# Data artifacts
data/bronze/landing/*.csv
data/bronze/raw/*.csv
data/silver/*
data/gold/*
!data/**/.gitkeep
*.db
*.sqlite
*.sqlite3

# Jupyter
.ipynb_checkpoints/
.jupyter/

# OS
.DS_Store

# Agent tooling
.opencode/
```

## Commit sequence (atomic, one feature per commit)

Never commit or push to `main`.

1. `chore: initialize repository`: `git init`, create branch `feat/etl-pipeline`, add `.gitignore`, `.env.example`, `README.md` skeleton, `docs/PLAN.md`.
2. `chore(deps): pin runtime and dev requirements`: add `requirements.txt`, `requirements-dev.txt`, `pyproject.toml` (pytest config), `Makefile`.
3. `feat(config): add env-driven settings and logging`: `src/violence_etl`, `settings.py`, `logging_conf.py`, `errors.py`, `tests/test_settings.py`.
4. `feat(db): add sqlalchemy models and engine factory`: `src/violence_etl`, `models.py`, `schema.py`.
5. `feat(migrations): add alembic setup and bronze migration`: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_bronze.py`.
6. `feat(bronze): download and land raw csv`: `src/violence_etl`, `bronze.py`, `tests/fixtures/*.csv`, `tests/test_bronze.py`.
7. `feat(silver): add period mapper`: `src/violence_etl`, `tests/test_periods.py`.
8. `feat(silver): curate, dedup and validate`: `migrations/versions/0002_silver.py`, `src/violence_etl`, `tests/test_silver.py`.
9. `feat(gold): add denormalized query tables`: `migrations/versions/0003_gold.py`, `src/violence_etl`, `tests/test_gold.py`.
10. `feat(cli): orchestrate the full pipeline`: `src/violence_etl`, `cli.py`, `tests/test_pipeline_sqlite.py`.
11. `docs: add analysis notebooks and usage guide`: `notebooks/01_bronze_profiling.ipynb`, `02_silver_validation.ipynb`, `03_gold_analysis.ipynb`, finalize `README.md` with the period table and gold SQL.

Run `make lint` (ruff, configured in `pyproject.toml`) and `python -m pytest tests -q` before each commit; both interpreters if available.

## Acceptance criteria (definition of done)

1. `python -m pytest tests -q` passes on Python 3.8 and on Python 3.14.
2. `PYTHONPATH=src python -m violence_etl.cli init-db` followed by `run-all` completes against SQLite (`ENV=DEV|TEST`) and against Azure PostgreSQL (`ENV=PROD` with `AZURE_KEYVAULT_URL` and Key Vault credentials) without code changes, only via environment configuration.
3. For the latest validated snapshot (local DEV, Docker, 2026-11-20), `bronze_crimes_raw` holds 15,981 rows for the source sha, every source field text, plus `source_url`, `load_ts`, `source_file`. Row counts can change as the source updates.
4. For the latest validated snapshot with `ETL_DEDUP_MODE=drop`, `silver_crimes` holds 14,460 rows, 1,521 duplicates are removed, and the run reports `rejected=0`, `total_crimes=15981`, `gold_grand_total=15981`. The chosen default and its effect are documented in `README.md`. Counts under `drop` and `sum` depend on the source snapshot.
5. Zero unmapped years: every `year` in 2003..2026 has a non-null `electoral_period`, and the mapper matches the 24-row table exactly.
6. `cod_depto` and `cod_muni` are never numeric: `SELECT cod_depto FROM silver_crimes LIMIT 1` returns a 2-char zero-padded string and `cod_muni` a 5-char one.
7. Re-running `run-all` twice changes no table row counts (idempotent).
8. Gold tables exist with the specified columns and keys: `gold_top5_departments` has 5 rows with ranks 1..5; `gold_crimes_by_department` has 32 rows; `gold_crimes_by_calendar` is unique on `(year, quarter, month, weekday_num)`; `gold_crimes_by_electoral_period` has 4 rows and `SUM(pct_of_total)` is 100.00 plus or minus rounding.
9. Grand totals agree: sum of `gold_crimes_by_department.total_crimes` equals sum of `gold_crimes_by_electoral_period.total_crimes` equals `SELECT SUM(cantidad) FROM silver_crimes` equals the run `gold_grand_total` (15,981 for the latest validated snapshot under the default policy).
10. Row-level rejects are visible in `silver_rejected_rows` with a reason; nothing is silently dropped.
11. `.gitignore` excludes `*.db`, `*.sqlite`, `.venv/`, `.idea/`, `.env`, and data artifacts; none of these are tracked.
12. All changes are on branch `feat/etl-pipeline`, committed in the order above with semantic prefixes.

## TODOs and follow-ups

This section records outstanding issues and backlog follow-ups from containerization and general project review. Items are not implemented here; they should be handled in future work (and specs updated via `@analyst`/orchestrator when required).

1. Dockerfile persisted data permissions (medium, `Dockerfile` around lines 22-23, `chmod -R a+rwx /app/data` after chown).
   Context: permissions are overly broad (world-writable) for persisted data dirs.
   Affected areas: `Dockerfile`, container runtime behavior for local bind mounts/named volumes.
   Follow-up: tighten to least privilege while preserving bind-mount/UID-GID workaround (for example narrower mode/group/setgid strategy, rely on documented `ETL_UID/GID` mapping, host chown/prep, or named volume; consider runtime ownership handling only if justified). Validation showed custom `ETL_UID=20001 ETL_GID=20001` on a fresh host dir can still fail if the host dir is not writable, so image chmod alone is insufficient.

2. First-run bind-mount permission guidance for Linux (medium, `docker-compose.yml` comments and `README.md` Docker/compose section).
   Context: custom UID/GID mapping alone may fail if the mounted host directory is not writable by that mapping.
   Affected areas: `docker-compose.yml`, `README.md`, developer onboarding for local DEV compose runs.
   Follow-up: make guidance more explicit (for example `mkdir -p data`, `ETL_UID=$(id -u) ETL_GID=$(id -g)` or chown, and when to prefer a named volume).

3. Docker reproducibility and build-context hygiene (low/nice-to-have, `Dockerfile` and `.dockerignore`).
   Context: current image/build setup works but has reproducibility and context trade-offs.
   Affected areas: `Dockerfile`, `.dockerignore`, CI/image build behavior.
   Follow-up: consider pinning base image by immutable digest (currently `python:3.12.12-slim` tag pinned), consider pinning/removing `pip install --upgrade pip` for stricter reproducibility, and optionally reconsider excluding `Dockerfile`/`docker-compose.yml` in `.dockerignore` (harmless now).

4. PYTHONPATH/src-layout package resolution (backlog).
   Context: running from IDE/CLI currently requires `PYTHONPATH=src` (for example `PYTHONPATH=src python -m violence_etl.cli init-db/run-[bronze|silver|gold|all]/drop-db`). Users should not need to set environment variables only to locate the package/runtime.
   Affected areas: project layout and packaging metadata (`pyproject.toml`/package discovery), CLI/docs/notebooks/dev workflows, possibly CI and tooling config.
   Follow-up: evaluate editable install/packaging or layout adjustment so `violence_etl` resolves without manual `PYTHONPATH`.

5. Makefile commands broken with current layout (resolved).
   Context: `make test` previously failed with `ModuleNotFoundError: No module named 'violence_etl'` because Makefile targets did not set `PYTHONPATH` for the `src/` layout.
   Affected areas: `Makefile` targets (`test`, `lint`, `init-db`, `run-all`, `sqlite-run`, `drop-db`), package resolution/setup, developer docs.
   Resolution: Makefile now defaults `PYTHONPATH ?= src`, exposes `PYTHON` override for CI (`make ... PYTHON=python`), adds `test-cov` and deterministic `ci-validate`, fixes `drop-db` tab indentation, and keeps existing local targets working. GitHub Actions CI uses these targets.

6. Lint baseline and import ordering (resolved).
   Context: `make lint` previously reported 28 existing ruff errors, mostly unsorted import blocks and missing trailing newlines.
   Affected areas: codebase-wide Python modules, `pyproject.toml`/ruff-isort configuration, CI/dev lint workflow.
   Resolution: fixed the import ordering/newline issues with `ruff check . --fix`, confirmed `ruff check .` passes cleanly, and kept behavior unchanged (test suite still passing).

10. GitHub Actions CI/CD (resolved by 0004).
    Context: the project needed automated lint, coverage, deterministic fixture validation, and controlled Docker publishing.
    Affected areas: `.github/workflows/ci.yml`, `Makefile`, `pyproject.toml`, `README.md`, CI operations/secrets/variables.
    Resolution: added CI workflow with `push`/`pull_request` triggers (`develop`, `main`, `feat/**`, `hotfix/**` / PRs to `develop`,`main`), `ruff` lint gate, `pytest-cov` with `--cov-fail-under=80` and `coverage.xml` artifact, deterministic `ci-validate` using committed fixture and temp SQLite/bronze paths, and a `docker-publish` job gated on validation success and `push` to `main`. Publish uses `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets and required `DOCKERHUB_REPOSITORY` variable, resolves semver from `pyproject.toml [project].version`, and pushes only `DOCKERHUB_REPOSITORY:<semver>` (no `:latest`). Required status check names must match the workflow/job check names exactly as they appear in GitHub for this workflow: `CI / lint`, `CI / test`, and `CI / pipeline-validate`; configure them in branch protection/rulesets for `develop` and `main`. Workflow failures alone do not block merges without branch protection/rulesets.

7. Dependency footprint review (backlog).
   Context: runtime and dev dependency sets should stay lean without breaking PROD/DEV workflows.
   Affected areas: `requirements.txt`, `requirements-dev.txt`, runtime image size/build time, Azure runtime deps, dev-only tools, notebook stack separation, markers/pins.
   Follow-up: review for unnecessary dependencies and adjust grouping/pins/markers while preserving supported Python range and PROD/DEV behavior.

8. Rename `src/violence_etl/storage/factory.py` to `storage_factory` (backlog, refactor).
   Context: module naming should better reflect purpose and be consistent with intended structure.
   Affected areas: `src/violence_etl/storage/factory.py`, all imports/references in code, tests, docs, and specs as applicable in the implementation task.
   Follow-up: perform coordinated rename and update references without behavior changes (tracked for implementation task/spec alignment).

9. Column naming standardization across layers (backlog, coordinated schema/contract refactor).
   Context: Spanish/English mix in core fields creates inconsistency across storage, code, and outputs.
   Affected areas: bronze/silver/gold tables and related layers (models, migrations, transformations, validations, storage/export schemas, CLI/output, tests, notebooks, docs).
   Proposed mapping: `fecha_hecho -> crime_date`, `cod_depto -> department_id`, `departamento -> department`, `cod_muni -> municipality_id`, `municipio -> municipality`, `zona -> zone`, `cantidad -> crime_count` (recommended; alternatives considered: `count`, `quantity`, `num_crimes` for clearer domain meaning).
   Follow-up: design and execute a coordinated schema/contract refactor and migration plan (future spec), including compatibility and data migration considerations.
