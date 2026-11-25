# Violence on Elections ETL

Medallion (bronze/silver/gold) ETL for the Colombian electoral-violence
dataset published on datos.gov.co (Socrata view `yi5j-5fe9`).

The pipeline downloads the source CSV, keeps it verbatim in a landing area,
mirrors it into a bronze table, curates and deduplicates it into silver, and
builds small denormalized gold tables ready for SQL or BI queries.

One codebase targets SQLite for local development and automated tests
(`ENV=DEV|TEST`) and Azure PostgreSQL for production (`ENV=PROD`). PostgreSQL
credentials are not read from local environment variables; in production they
are fetched from Azure Key Vault. The design and rationale live in
`docs/PLAN.md`; this file is the usage guide.

## Quickstart (SQLite)

```
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

PYTHONPATH=src ENV=DEV .venv/bin/python -m violence_etl.cli init-db
PYTHONPATH=src ENV=DEV .venv/bin/python -m violence_etl.cli run-all
PYTHONPATH=src ENV=DEV .venv/bin/python -m violence_etl.cli validate
```

`ENV` defaults to `DEV`, so `ENV=DEV` can be omitted for local runs. The
package lives under `src/` (no editable install step is configured), so run
CLI commands from the repository root with `PYTHONPATH=src`. The first
`run-all` downloads the source and needs network access. Expected tail of a
fresh first run on the latest validated snapshot (local DEV, Docker, 2026-11-20):

```
run-all: bronze_status=loaded raw_rows=15981 silver_rows=14460 rejected=0 dropped_duplicates=1521 total_crimes=15981 gold_grand_total=15981
```

Expected `validate` for that snapshot:

```
[ok] bronze rows: 15981
[ok] silver rows: 14460
[ok] rejected rows: 0
[ok] silver total == gold dept total: (15981, 15981)
[ok] gold dept total == gold period total: (15981, 15981)
[ok] top5 has 5 rows: 5
[ok] by-department rows: 32
[ok] period table has 4 rows: 4
[ok] calendar grain unique: 0
[ok] cod_depto is 2 chars: 05
[ok] cod_muni is 5 chars: 05660
validate: PASS
```

The pipeline is idempotent. A second `run-all` on the same source skips bronze
and changes no row counts in any table:

```
run-all: bronze_status=skipped raw_rows=15981 silver_rows=14460 rejected=0 dropped_duplicates=1521 total_crimes=15981 gold_grand_total=15981
```

The corresponding `silver:` log line on that second run reports `inserted=0`,
because the insert rowcount is zero when every business key already exists.

## Docker (local DEV)

The repository includes a runtime-only image (`python:3.12.12-slim`, pinned) and
`docker-compose.yml` for local runs. The image copies `src/`, `migrations/`,
`alembic.ini`, and `requirements.txt`, sets `PYTHONPATH=/app/src` and
`PYTHONUNBUFFERED=1`, and runs as a non-root user.

Build the image:

```
docker build -t violence-etl:dev .
```

Default container command behavior:

```
python -m violence_etl.cli init-db && python -m violence_etl.cli run-all
```

`init-db` runs Alembic migrations to head and is idempotent/non-destructive.
`--export-csv` is off by default and only runs when explicitly passed.

Local compose usage (SQLite with mounted persistence under `/app/data`):

```
docker compose run --rm etl
docker compose run --rm etl python -m violence_etl.cli validate
```

Override examples (overrides replace the whole default command chain):

```
# default chain with gold CSV export
docker compose run --rm etl sh -c "python -m violence_etl.cli init-db && python -m violence_etl.cli run-all --export-csv"

# validation only (no implicit init-db)
docker compose run --rm etl python -m violence_etl.cli validate

# targeted/local-input run (mount input under ./data, include init-db when needed)
docker compose run --rm etl sh -c "python -m violence_etl.cli init-db && python -m violence_etl.cli ingest-bronze --csv-path /app/data/input.csv"
```

Because overrides replace the whole chained default, maintenance/targeted
commands do not implicitly include `init-db` unless included in the override.

The default compose mount is `./data:/app/data`, which persists the SQLite
database and local bronze/gold artifacts across runs. On Linux, bind mounts can
inherit host ownership that is not writable by the container user
(default uid/gid 10001). Use `ETL_UID`/`ETL_GID` (for example
`ETL_UID=$(id -u) ETL_GID=$(id -g) docker compose run --rm etl`), pre-create and
chown `./data`, or switch to a named volume as shown in `docker-compose.yml`.
Local `data/` persistence is a DEV/TEST concern.

## Azure Container Apps Job (PROD)

The same image is intended to run as a monthly run-to-completion Azure Container
Apps Job. Use the default command unless an explicit operational override is
required. Configure `ENV=PROD` and `AZURE_KEYVAULT_URL`; the application uses
`DefaultAzureCredential`/managed identity to read PostgreSQL and blob storage
configuration from Key Vault and to access Azure PostgreSQL and Azure Blob
Storage (existing behavior, with `sslmode=require` for PostgreSQL). No data
volume is required or expected in PROD because artifact persistence uses Blob
Storage and the container filesystem is ephemeral. Missing required PROD
configuration/secrets, auth failures, or unreachable dependencies fail fast and
surface as job failure (non-zero exit). Do not bake secrets or local data into
the image. Pass runtime configuration and identities through the job/platform.

## Stack and compatibility

Python 3.8 through 3.14 from one source tree, Azure PostgreSQL as the
production warehouse, SQLite for local development and tests, Alembic
migrations, SQLAlchemy ORM, Pandas, PyTest and Jupyter notebooks.

Compatibility rules used in the code: `from __future__ import annotations`,
`typing.List`/`Optional`/`Dict`, SQLAlchemy classic `Column(...)` style, and no
`schema`-qualified tables (table-name prefixes instead, because SQLite has no
schemas). `requirements.txt` uses environment markers because no single
pandas/numpy pin spans 3.8 to 3.14 with wheels.

The runtime pins:

```
SQLAlchemy==2.0.44
alembic==1.14.1
psycopg==3.2.10
psycopg-binary==3.2.10
numpy==1.24.4;      python_version < "3.9"
pandas==2.0.3;      python_version < "3.9"
numpy==2.0.2;       python_version >= "3.9" and python_version < "3.11"
pandas==2.3.3;      python_version >= "3.9"
numpy==2.3.2;       python_version >= "3.11"
requests==2.31.0
python-dotenv==1.0.1
azure-identity==1.17.1
azure-keyvault-secrets==4.8.0
azure-storage-blob==12.22.0
```

`azure-identity` and `azure-keyvault-secrets` are used in `ENV=PROD` to fetch
PostgreSQL credentials and blob storage configuration from Azure Key Vault.
`azure-storage-blob` is used in `ENV=PROD` for bronze and gold CSV artifact
storage. Azure SDK imports are lazy, so `DEV`/`TEST` local flows do not require
these packages at runtime. `requirements-dev.txt` adds
`pytest`, `ruff`, `pytest-cov`, `coverage` and the Jupyter stack
(`jupyterlab`, `notebook`, `ipykernel`). The coverage and Jupyter pins are
split by interpreter range with the same markers.

## Install

```
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements.txt` holds runtime dependencies, `requirements-dev.txt` adds the
dev and notebook tools. `make install` runs the last two commands.

## Configuration

All settings come from environment variables (or a local `.env`, which is
gitignored). `.env.example` lists them.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENV` | `DEV` | Runtime environment: `DEV`, `TEST`, or `PROD` |
| `AZURE_KEYVAULT_URL` | unset | Azure Key Vault URL (required when `ENV=PROD`) |
| `ETL_SQLITE_PATH` | `data/warehouse/violence_staging.db` | SQLite database file (used in `DEV`/`TEST`) |
| `ETL_SOURCE_URL` | `http://www.datos.gov.co/api/v3/views/yi5j-5fe9/export.csv` | download source |
| `ETL_LOG_LEVEL` | `INFO` | root log level |
| `ETL_DEDUP_MODE` | `drop` | `drop` or `sum` duplicate policy |
| `ETL_BRONZE_DIR` | `data/bronze` | local landing/raw root for `DEV`/`TEST` |

Environment behavior:

- `ENV=DEV` or `ENV=TEST`: the pipeline uses SQLite at `ETL_SQLITE_PATH`. This
  is the path for local development and automated tests.
- `ENV=PROD`: the pipeline uses Azure PostgreSQL and Azure Blob Storage for
  CSV artifacts. Credentials and storage configuration are fetched from Azure
  Key Vault at `AZURE_KEYVAULT_URL` using `DefaultAzureCredential`. The Key
  Vault must contain the database secrets `PGHOST`, `PGPORT`, `PGUSER`,
  `PGPASSWORD`, and `PGDATABASE`, and the blob storage secrets
  `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER`.
  The PostgreSQL connection is created with `sslmode=require`. Bronze and gold
  CSV artifacts are stored in blob containers (landing/raw in the bronze
  container, gold exports in the gold container root). `SILVCONTAINER` is
  retrieved and configured now as a reserved location for future silver CSV
  artifacts. Local `data/` artifact paths apply to `DEV`/`TEST`.

PostgreSQL credentials are not read from local environment variables and there
is no `DATABASE_URL` override. Blob container names and storage account name
for `PROD` are also resolved from Key Vault. This keeps production credentials
and storage configuration in Key Vault only.

Generic Key Vault reads live in `src/violence_etl/clients/key_vault.py` as
`KeyVaultClient`. It works for any secret and imports the Azure SDK only when
needed. PostgreSQL specifics live in `src/violence_etl/config/settings.py`:
`postgres_url_from_key_vault()` reads the five secrets, parses `PGPORT`, and
builds the `postgresql+psycopg` URL with `sslmode=require`;
`database_url_object()` calls it for `PROD`.

The CLI global flags are `--sqlite-path PATH` (sets `ETL_SQLITE_PATH` for this
run) and `--log-level LEVEL` (sets `ETL_LOG_LEVEL` for this run).

## Running against Azure PostgreSQL (PROD)

Production targets an Azure PostgreSQL database. Configure access and run:

```
export ENV=PROD
export AZURE_KEYVAULT_URL=https://violencekv.vault.azure.net/
export PYTHONPATH=src

python -m violence_etl.cli init-db
python -m violence_etl.cli run-all
python -m violence_etl.cli validate
```

Requirements:

- The process must be able to authenticate with Azure using
  `DefaultAzureCredential` (for example via Azure CLI login, managed identity,
  or supported environment-based credentials).
- The Key Vault must expose database secrets named `PGHOST`, `PGPORT`,
  `PGUSER`, `PGPASSWORD`, and `PGDATABASE`, and blob storage secrets named
  `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER`.
- Network access to the Key Vault, the PostgreSQL server, and the storage
  account must be available. The database connection uses
  `postgresql+psycopg://...?...sslmode=require` and blob access uses
  `https://<STORAGEACCOUNT>.blob.core.windows.net` with
  `DefaultAzureCredential`.

`init-db` runs the migrations. The equivalent direct Alembic command, from the
repository root with the same environment, is:

```
PYTHONPATH=src alembic upgrade head
```

`migrations/env.py` reads `violence_etl` settings, so the same migration
history runs on SQLite and PostgreSQL. The CLI resolves `alembic.ini` and
`migrations/` from the repository root via `REPO_ROOT` (defined in
`src/violence_etl/cli.py` and in the package `__init__` modules). The history
has four revisions: `0001_bronze`, `0002_silver`, `0003_gold` and
`0004_bronze_ingestion_unique`, which adds `UNIQUE(source_sha256)` to
`bronze_ingestion_log`. Useful Alembic commands: `alembic current`,
`alembic history`, `alembic downgrade base`.

## CLI reference

Entry point (from the repository root, with the package on the path):
`PYTHONPATH=src python -m violence_etl.cli <command>`. Global flags go before
the command:

- `--sqlite-path PATH`: sets `ETL_SQLITE_PATH` for this run (used in
  `DEV`/`TEST`).
- `--log-level LEVEL`: sets `ETL_LOG_LEVEL` for this run.

Commands and their flags:

| Command | Flags | What it does |
| --- | --- | --- |
| `init-db` | none | run `alembic upgrade head` for the configured environment |
| `download` | none | fetch the CSV, persist the landing artifact, and print the sha256 and location |
| `ingest-bronze` | `--csv-path PATH`, `--force` | load bronze only |
| `build-silver` | `--sha SHA`, `--force` | build silver only |
| `build-gold` | `--export-csv` | build gold only |
| `run-all` | `--csv-path PATH`, `--force`, `--export-csv` | bronze, then silver, then gold |
| `validate` | none | print the acceptance checks |
| `drop-db` | `--yes` | drop and recreate all tables (dev only) |

Notes:

- Without `--csv-path`, `ingest-bronze` and `run-all` download
  `ETL_SOURCE_URL`. With it, they read that local file and still hash its bytes.
  In `PROD`, the resulting bronze artifacts are written to blob storage.
- `--force` on bronze reloads the raw rows; on silver it rebuilds the active
  snapshot. See the idempotency section.
- `--sha` on `build-silver` picks a specific bronze snapshot; the default is the
  most recent snapshot in `bronze_crimes_raw`.
- `build-gold --export-csv` and `run-all --export-csv` write the four gold CSVs
  in addition to the tables: to `data/gold/*.csv` in `DEV`/`TEST`, or to the
  `GOLDCONTAINER` root in `PROD` (`export_dir` applies to local `DEV`/`TEST`
  exports only).
- `drop-db` refuses to run without `--yes` and returns exit code 2.

## Tables

A migrated database has nine tables: the eight application tables below plus
the Alembic bookkeeping table `alembic_version`.

Landing and raw artifacts:

- `DEV`/`TEST` (local): `data/bronze/landing/<sha256>.csv` stores the verbatim
  downloaded bytes named by content hash, `data/bronze/raw/yi5j-5fe9_<utcstamp>.csv`
  stores the run-stamped copy, and `data/gold/*.csv` stores optional exports
  written by `--export-csv`.
- `PROD` (blob): bronze landing and raw artifacts are stored in `BRZECONTAINER`
  as `landing/<sha256>.csv` and `raw/yi5j-5fe9_<utcstamp>.csv`. When
  `--export-csv` is used, gold files are written to the `GOLDCONTAINER` root
  with the same filenames (`gold_top5_departments.csv`,
  `gold_crimes_by_department.csv`, `gold_crimes_by_calendar.csv`,
  `gold_crimes_by_electoral_period.csv`). In `PROD`, reported bronze artifact
  locations (`source_file`, download landing location) are blob names within the
  bronze container.

Bronze tables:

- `bronze_crimes_raw`: every source field stored as text plus ingestion
  metadata. Columns: `raw_id` (primary key), `source_sha256`, `source_file`,
  `source_url`, `load_ts`, `row_num` (1-based), `fecha_hecho_raw`,
  `cod_depto_raw`, `departamento_raw`, `cod_muni_raw`, `municipio_raw`,
  `zona_raw`, `cantidad_raw`. Unique on `(source_sha256, row_num)`.
- `bronze_ingestion_log`: one row per source content hash. Columns:
  `ingestion_id` (primary key), `source_url`, `source_file`, `source_sha256`
  (unique), `row_count`, `status` (`loaded`, `skipped` or `failed`), `message`,
  `loaded_at`. Reloads update this row in place, so it never grows on repeated
  attempts.

Silver tables:

- `silver_crimes`: typed, trimmed, uppercased, code-preserving, deduplicated,
  validated, calendar-enriched rows. Columns: `id` (primary key),
  `fecha_hecho`, `cod_depto`, `departamento`, `cod_muni`, `municipio`, `zona`,
  `cantidad`, `year`, `month`, `quarter`, `weekday_num`, `weekday_name`,
  `electoral_period`, `row_hash`, `source_sha256`, `silver_loaded_at`. Unique on
  `(fecha_hecho, cod_depto, cod_muni, zona, cantidad)`. Holds a single active
  snapshot: rows for other `source_sha256` values are purged on load.
- `silver_rejected_rows`: every rejected row with a reason and its raw values.
  Columns: `id` (primary key), `source_sha256`, `row_num`, `reject_reason`,
  `raw_values` (JSON string), `rejected_at`.

## Gold table catalogue

Gold is rebuilt by full refresh (delete then aggregate-insert) from the active
silver snapshot, so it always converges to the same content. Each table below
lists its columns and the question it answers.

`gold_top5_departments`: top 5 departments by total crimes. Columns: `rank`
(primary key, 1..5), `cod_depto`, `departamento`, `total_crimes`. Ranked by
`total_crimes DESC`, ties broken by `departamento ASC`.

```sql
SELECT rank, departamento, total_crimes
FROM gold_top5_departments
ORDER BY rank;
```

`gold_crimes_by_department`: total crimes for every department. Columns:
`cod_depto` (primary key), `departamento`, `total_crimes`.

```sql
SELECT cod_depto, departamento, total_crimes
FROM gold_crimes_by_department
ORDER BY total_crimes DESC;
```

`gold_crimes_by_calendar`: total crimes per calendar bucket. Columns: `year`,
`quarter`, `month`, `weekday_num` (composite primary key), `weekday_name`,
`total_crimes`. Grain is `year x quarter x month x weekday_num`, unique.

```sql
SELECT year, quarter, month, weekday_num, weekday_name, total_crimes
FROM gold_crimes_by_calendar
ORDER BY year, quarter, month, weekday_num;
```

`gold_crimes_by_electoral_period`: total crimes per electoral period. Columns:
`electoral_period` (primary key), `period_order`, `year_min`, `year_max`,
`total_crimes`, `pct_of_total`. `period_order` uses the presentation order
post, intermediate, pre, electoral. `pct_of_total` is the share of the grand
total, rounded to 2 decimals.

```sql
SELECT electoral_period, period_order, year_min, year_max,
       total_crimes, pct_of_total
FROM gold_crimes_by_electoral_period
ORDER BY period_order;
```

Equivalent plain SQL over `silver_crimes`:

```sql
-- total crimes by department
SELECT cod_depto, departamento, SUM(cantidad) AS total_crimes
FROM silver_crimes
GROUP BY cod_depto, departamento
ORDER BY total_crimes DESC;

-- total crimes by year, quarter, month and weekday
SELECT year, quarter, month, weekday_num, weekday_name, SUM(cantidad) AS total_crimes
FROM silver_crimes
GROUP BY year, quarter, month, weekday_num, weekday_name;

-- total crimes by electoral period
SELECT electoral_period, SUM(cantidad) AS total_crimes
FROM silver_crimes
GROUP BY electoral_period;
```

## Cleaning and deduplication

Silver applies, in order: strip whitespace; uppercase `departamento`,
`municipio` and `zona`; keep `cod_depto`/`cod_muni` as zero-padded text
(2 and 5 chars); parse `fecha_hecho` with the explicit `%d/%m/%Y` format;
cast `cantidad` to integer (fractional values such as `1.5` are rejected);
restrict `zona` to `URBANA`/`RURAL`; reject null or empty business fields;
reject a `cod_depto` that is not the first two characters of `cod_muni`; then
deduplicate. Every empty value, including an empty code, is reported as
`null_field`; the type rules only flag non-empty invalid values. Every rejected
row is written to `silver_rejected_rows` with a reason, so nothing is silently
lost. The literal rule order is documented in `docs/PLAN.md`.

Deduplication is keyed on `(fecha_hecho, cod_depto, cod_muni, zona, cantidad)`,
because `departamento` and `municipio` are functionally dependent on the codes.

The default policy is `drop`, which keeps one row per business key. Repeated
identical rows are treated as ingestion duplication, not distinct events,
because the source has no event id. Counts change as the source snapshot
updates; on the latest validated snapshot (local DEV, Docker, 2026-11-20) this
removed 1,521 exact duplicate rows (9.52 percent): 15,981 raw rows became
14,460 silver rows, with `rejected=0`, `total_crimes=15981`, and
`gold_grand_total=15981`.

`ETL_DEDUP_MODE=sum` groups by the key without `cantidad` and sums `CANTIDAD`.
It is intended for datasets where `CANTIDAD` is a real magnitude and duplicate
rows are partial reports. Row and total counts under `sum` depend on the source
snapshot; verify by running with `ETL_DEDUP_MODE=sum`.

## Electoral period mapping

The mapper uses Colombian general elections every 4 years (2002, 2006, 2010,
2014, 2018, 2022, 2026). Labels are `pre-electoral` (one year before),
`electoral` (election year), `post-electoral` (one year after) and
`intermediate` (the remaining year). Years before 2001 are `unclassified`.

| Year | Period | Year | Period |
| --- | --- | --- | --- |
| 2003 | post-electoral | 2015 | post-electoral |
| 2004 | intermediate | 2016 | intermediate |
| 2005 | pre-electoral | 2017 | pre-electoral |
| 2006 | electoral | 2018 | electoral |
| 2007 | post-electoral | 2019 | post-electoral |
| 2008 | intermediate | 2020 | intermediate |
| 2009 | pre-electoral | 2021 | pre-electoral |
| 2010 | electoral | 2022 | electoral |
| 2011 | post-electoral | 2023 | post-electoral |
| 2012 | intermediate | 2024 | intermediate |
| 2013 | pre-electoral | 2025 | pre-electoral |
| 2014 | electoral | 2026 | electoral |

Every year in the data range is classified. The full table is asserted in
`tests/test_periods.py`, so the mapper cannot silently drift.

## Idempotency and reload semantics

The pipeline is safe to run repeatedly.

- Bronze is keyed on the content sha256. Reload detection uses the presence of
  raw rows, not the log status: if `bronze_crimes_raw` already holds rows for
  that hash and `--force` is not set, the raw rows are left untouched and the
  single `bronze_ingestion_log` row for that hash is updated in place with
  `status="skipped"`. `--force` reloads the raw rows and updates that same log
  row with `status="loaded"`, so the log never grows on repeated attempts.
- Silver holds exactly one active snapshot: the rows for the active sha256. On
  each run rows from any other sha256 are purged, then the current snapshot is
  inserted with business-key conflicts ignored (`ON CONFLICT DO NOTHING` on
  PostgreSQL, `INSERT OR IGNORE` on SQLite). Loading an updated export replaces
  the previous one instead of mixing snapshots, and a second run of the same
  export writes zero new rows. Reported counts come from the database after the
  write: `inserted_rows` is the insert rowcount and `silver_rows`/`total_crimes`
  are read back from the active snapshot.
- `silver_rejected_rows` is rebuilt for the active sha256 on every run.
- Gold is a full refresh (delete then aggregate-insert), so it always converges
  to the same content and always reflects the single active snapshot.

A second `run-all` on the same source logs `skipped` at bronze and changes no
row counts in any table.

## Tests

```
python -m pytest tests -q
python -m pytest tests -q --cov=violence_etl --cov-report=term-missing
python -m pytest tests/test_periods.py -q
```

The suite runs fully offline against SQLite using the committed fixtures
(`ENV=TEST` in test configuration). The current result is 102 passed and 1
skipped. The skipped test is a slow, network-backed run against the real
dataset; enable it with `ETL_FULL_DATASET=1`:

```
ETL_FULL_DATASET=1 python -m pytest tests -q -m full_dataset
```

`make test` runs `python -m pytest tests -q`, and `make lint` runs
`python -m ruff check .`.

## Notebooks

The notebooks under `notebooks/` are meant to be run on the PyCharm IDE Managed
Jupyter server, with the project `.venv` as the kernel. No separate
`jupyter notebook` process is needed.

1. Open the project in PyCharm and go to `Settings > Project > Python Interpreter`.
2. Select the project virtualenv `.venv` as the interpreter.
3. If PyCharm offers to install the Jupyter section, accept. PyCharm then
   starts and manages the Jupyter server for you.
4. Open a notebook. In the notebook toolbar, choose the managed server as the
   Jupyter server and select the project `.venv` interpreter as the kernel.
5. Run the cells, starting with the bootstrap cell.

Each notebook bootstrap sets `ENV=DEV` so it uses the local SQLite database and
never touches PostgreSQL. The notebook stack lives in `requirements-dev.txt`.
See `notebooks/README.md` for the notebook list and prerequisites.

## CI/CD (GitHub Actions)

The workflow `.github/workflows/ci.yml` runs on:

- `push` to `develop`, `main`, `feat/**`, and `hotfix/**`
- `pull_request` targeting `develop` and `main`

Required validation jobs:

- `lint`: `make lint PYTHON=python` (`ruff check .`)
- `test`: `make test-cov PYTHON=python` with `--cov-fail-under=80`, terminal
  coverage summary, and `coverage.xml` uploaded as the `coverage-xml` artifact
- `pipeline-validate`: `make ci-validate PYTHON=python`, which runs deterministic
  fixture validation with `ENV=TEST`, clean temporary SQLite DB and bronze paths,
  and the committed fixture `tests/fixtures/yi5j-5fe9_sample.csv` through
  `init-db`, `run-all --csv-path ...`, and `validate` (no external download)

Docker publish runs only on `push` to `main` and only after `lint`, `test`, and
`pipeline-validate` succeed. It resolves semver from `pyproject.toml`
`[project].version`, fails fast if that version is missing/empty/invalid, fails
fast if the GitHub repository variable `DOCKERHUB_REPOSITORY` is missing/empty,
logs in with GitHub secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, and
pushes only `DOCKERHUB_REPOSITORY:<semver>`. No `:latest` tag is published.

Required GitHub repository settings (names only, no values):

- Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- Variable: `DOCKERHUB_REPOSITORY`

Merge blocking requires GitHub branch protection or repository rulesets that
require the CI status checks. Workflow failures alone do not block merges.
Configure required checks for the jobs used by this workflow (for example
`lint`, `test`, and `pipeline-validate`).

Local reproduction commands:

```
make lint PYTHON=python
make test-cov PYTHON=python
make ci-validate PYTHON=python
```

## Makefile

The Makefile defaults to `PYTHON ?= .venv/bin/python` and `PYTHONPATH ?= src`.
CI overrides with `PYTHON=python`. Targets that invoke the package/tests set
`PYTHONPATH` explicitly.

- `make install`: upgrade pip and install `requirements-dev.txt`.
- `make lint`: `ruff check .`.
- `make test`: `pytest tests -q`.
- `make test-cov`: pytest with coverage for `violence_etl`,
  `--cov-fail-under=80`, terminal missing summary, and `coverage.xml`.
- `make ci-validate`: deterministic fixture validation in a clean temp area
  (`CI_TMP_DIR`, default `${TMPDIR:-/tmp}/violence-etl-ci`, overridable). It runs
  `init-db`, `run-all --csv-path tests/fixtures/yi5j-5fe9_sample.csv`, and
  `validate` with `ENV=TEST` and temp `ETL_SQLITE_PATH`/`ETL_BRONZE_DIR`.
- `make init-db`: `python -m violence_etl.cli init-db`.
- `make drop-db`: `python -m violence_etl.cli drop-db`.
- `make run-all`: `python -m violence_etl.cli run-all`.
- `make sqlite-run`: `init-db` then `run-all` against
  `data/warehouse/violence_staging.db` with `ENV=DEV`.

Examples:

```
make lint PYTHON=python
make test-cov PYTHON=.venv/bin/python
PYTHONPATH=src make sqlite-run
```

## Troubleshooting

- `ModuleNotFoundError: No module named 'violence_etl'`: the package is under
  `src/`. Run commands from the repository root with `PYTHONPATH=src` (for
  example, `PYTHONPATH=src python -m violence_etl.cli ...`), or install the
  project in editable mode once packaging is configured. Do not run
  `python -m src.violence_etl.cli`, because internal imports use the
  `violence_etl.*` package name. See TODO items 4-5 in `docs/PLAN.md`.
- `AZURE_KEYVAULT_URL is required when ENV=PROD`: set `AZURE_KEYVAULT_URL` to
  the vault URL (for example `https://violencekv.vault.azure.net/`).
- `init-db` or `run-all` fails in `PROD` with Azure auth errors: ensure
  `DefaultAzureCredential` can authenticate in the current environment and that
  the identity has permission to read secrets in the vault.
- A command fails in `PROD` with missing/empty secret errors: verify the vault
  contains `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`,
  `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER`. Blob
  storage secrets are validated when settings load in `PROD`, so missing or
  empty values fail fast.
- PostgreSQL connection errors in `PROD`: verify the host/database values from
  Key Vault, network/firewall rules, and that the server accepts TLS
  connections (`sslmode=require` is enforced).
- A repeat run does not reload bronze: use `--force`.
- `SchemaError` on ingest: the CSV header must match
  `FECHA HECHO,COD_DEPTO,DEPARTAMENTO,COD_MUNI,MUNICIPIO,ZONA,CANTIDAD` exactly,
  in order and case.
- A notebook cannot import `violence_etl`: run the bootstrap cell first, ensure
  the kernel is using the project `.venv`, and confirm the notebook can resolve
  the `violence_etl` package in your environment. If imports still fail, check
  that ORM models import `Base` from `violence_etl.db.models.base_model`.
- Docker/compose Linux bind-mount permissions and other follow-ups are tracked in `docs/PLAN.md` (`## TODOs and follow-ups`).

## Known limitations

- The production PostgreSQL path and Azure Blob artifact storage use Azure Key
  Vault, `DefaultAzureCredential`, and `sslmode=require`, and require Azure
  authentication and network access to the vault, database, and storage
  account; they have not been executed locally in this environment. Local runs
  and automated tests use SQLite and local `data/` artifacts
  (`ENV=DEV|TEST`).
- The code and dependency markers target Python 3.8 through 3.14, but only
  Python 3.14 has been executed locally. Versions 3.8 through 3.13 have not
  been run here.
- The `full_dataset` test needs network access and `ETL_FULL_DATASET=1`.
