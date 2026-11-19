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
`run-all` downloads the source and needs network access. Expected tail of the
first run:

```
run-all: bronze_status=loaded raw_rows=15696 silver_rows=14212 rejected=0 dropped_duplicates=1484 total_crimes=14212 gold_grand_total=14212
```

Expected `validate`:

```
[ok] bronze rows: 15696
[ok] silver rows: 14212
[ok] rejected rows: 0
[ok] silver total == gold dept total: (14212, 14212)
[ok] gold dept total == gold period total: (14212, 14212)
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
run-all: bronze_status=skipped raw_rows=15696 silver_rows=14212 rejected=0 dropped_duplicates=1484 total_crimes=14212 gold_grand_total=14212
```

The corresponding `silver:` log line on that second run reports `inserted=0`,
because the insert rowcount is zero when every business key already exists.

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
```

`azure-identity` and `azure-keyvault-secrets` are used in `ENV=PROD` to fetch
PostgreSQL credentials from Azure Key Vault. `requirements-dev.txt` adds
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
| `ETL_BRONZE_DIR` | `data/bronze` | landing/raw root |

Environment behavior:

- `ENV=DEV` or `ENV=TEST`: the pipeline uses SQLite at `ETL_SQLITE_PATH`. This
  is the path for local development and automated tests.
- `ENV=PROD`: the pipeline uses Azure PostgreSQL. Credentials are fetched from
  Azure Key Vault at `AZURE_KEYVAULT_URL` using `DefaultAzureCredential`. The
  Key Vault must contain the secrets `PGHOST`, `PGPORT`, `PGUSER`,
  `PGPASSWORD`, and `PGDATABASE`. The PostgreSQL connection is created with
  `sslmode=require`.

PostgreSQL credentials are not read from local environment variables and there
is no `DATABASE_URL` override. This keeps production credentials in Key Vault
only.

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
- The Key Vault must expose secrets named `PGHOST`, `PGPORT`, `PGUSER`,
  `PGPASSWORD`, and `PGDATABASE`.
- Network access to the Key Vault and the PostgreSQL server must be available.
  The connection uses `postgresql+psycopg://...?...sslmode=require`.

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
| `download` | none | fetch the CSV to `data/bronze/landing` and print the sha256 |
| `ingest-bronze` | `--csv-path PATH`, `--force` | load bronze only |
| `build-silver` | `--sha SHA`, `--force` | build silver only |
| `build-gold` | `--export-csv` | build gold only |
| `run-all` | `--csv-path PATH`, `--force`, `--export-csv` | bronze, then silver, then gold |
| `validate` | none | print the acceptance checks |
| `drop-db` | `--yes` | drop and recreate all tables (dev only) |

Notes:

- Without `--csv-path`, `ingest-bronze` and `run-all` download
  `ETL_SOURCE_URL`. With it, they read that local file and still hash its bytes.
- `--force` on bronze reloads the raw rows; on silver it rebuilds the active
  snapshot. See the idempotency section.
- `--sha` on `build-silver` picks a specific bronze snapshot; the default is the
  most recent snapshot in `bronze_crimes_raw`.
- `build-gold --export-csv` writes `data/gold/*.csv` in addition to the tables.
- `drop-db` refuses to run without `--yes` and returns exit code 2.

## Tables

A migrated database has nine tables: the eight application tables below plus
the Alembic bookkeeping table `alembic_version`.

Landing and raw artifacts on disk:

- `data/bronze/landing/<sha256>.csv`: the verbatim downloaded bytes, named by
  content hash, never edited.
- `data/bronze/raw/yi5j-5fe9_<utcstamp>.csv`: a run-stamped copy referenced by
  the ingestion log.
- `data/gold/*.csv`: optional exports written by `--export-csv`.

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
because the source has no event id and `CANTIDAD` is always 1. On the verified
dataset this removes 1,484 exact duplicates: 15,696 raw rows become 14,212
silver rows and the crime total goes from 15,696 to 14,212.

`ETL_DEDUP_MODE=sum` groups by the key without `cantidad` and sums `CANTIDAD`.
On this dataset it keeps 14,212 rows and a total of 15,696, because every
duplicate group sums back to its own count. It is intended for datasets where
`CANTIDAD` is a real magnitude and duplicate rows are partial reports.

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
(`ENV=TEST` in test configuration). The current result is 85 passed and 1
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

## Makefile

- `make install`: upgrade pip and install `requirements-dev.txt`.
- `make test`: `python -m pytest tests -q`.
- `make lint`: `python -m ruff check .`.
- `make init-db`: `python -m violence_etl.cli init-db`.
- `make run-all`: `python -m violence_etl.cli run-all`.
- `make sqlite-run`: `init-db` then `run-all` against
  `data/warehouse/violence_staging.db` with `ENV=DEV`.

The CLI targets invoke `python -m violence_etl.cli` directly. With the current
`src/` layout (no editable install), run them with `PYTHONPATH=src` in the
environment, for example `PYTHONPATH=src make sqlite-run`, or use the explicit
CLI commands shown above.

## Troubleshooting

- `ModuleNotFoundError: No module named 'violence_etl'`: the package is under
  `src/`. Run commands from the repository root with `PYTHONPATH=src` (for
  example, `PYTHONPATH=src python -m violence_etl.cli ...`), or install the
  project in editable mode once packaging is configured. Do not run
  `python -m src.violence_etl.cli`, because internal imports use the
  `violence_etl.*` package name.
- `AZURE_KEYVAULT_URL is required when ENV=PROD`: set `AZURE_KEYVAULT_URL` to
  the vault URL (for example `https://violencekv.vault.azure.net/`).
- `init-db` or `run-all` fails in `PROD` with Azure auth errors: ensure
  `DefaultAzureCredential` can authenticate in the current environment and that
  the identity has permission to read secrets in the vault.
- `init-db` or `run-all` fails in `PROD` with missing/empty secret errors:
  verify the vault contains `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and
  `PGDATABASE`.
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

## Known limitations

- The production PostgreSQL path uses Azure Key Vault and `sslmode=require` and
  requires Azure authentication and network access to the vault and database; it
  has not been executed locally in this environment. Local runs and automated
  tests use SQLite (`ENV=DEV|TEST`).
- The code and dependency markers target Python 3.8 through 3.14, but only
  Python 3.14 has been executed locally. Versions 3.8 through 3.13 have not
  been run here.
- The `full_dataset` test needs network access and `ETL_FULL_DATASET=1`.
