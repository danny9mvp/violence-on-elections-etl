# Violence on Elections ETL

Medallion (bronze/silver/gold) ETL for the Colombian electoral-violence
dataset published on datos.gov.co (Socrata view `yi5j-5fe9`).

The pipeline downloads the source CSV, lands it verbatim, mirrors it into a
bronze table, curates and deduplicates it into a silver table, and builds
small denormalized gold tables ready for SQL or BI queries.

One codebase runs against PostgreSQL (warehouse) and SQLite (staging/tests).
The target is selected with environment variables, so no code change is needed
to switch. See `docs/PLAN.md` for the full design.

## Stack

Python 3.8 through 3.14 from one source tree, PostgreSQL LTS as warehouse,
SQLite for staging and tests, Alembic migrations, SQLAlchemy ORM, Pandas,
PyTest and Jupyter notebooks.

Compatibility rules used in the code: `from __future__ import annotations`,
`typing.List`/`Optional`/`Dict`, SQLAlchemy classic `Column(...)` style, and no
`schema`-qualified tables (table-name prefixes instead, because SQLite has no
schemas). `requirements.txt` uses environment markers because no single
pandas/numpy pin spans 3.8 to 3.14 with wheels.

## Install

```
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements.txt` holds runtime dependencies, `requirements-dev.txt` adds
pytest, coverage, ruff and the Jupyter stack.

## Configuration

All settings come from environment variables (or a local `.env`, which is
gitignored). `.env.example` lists them with the defaults.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ETL_DB_BACKEND` | `postgres` | `postgres` or `sqlite` |
| `PGHOST` | `localhost` | warehouse host |
| `PGPORT` | `5432` | warehouse port |
| `PGUSER` | `postgres` | warehouse user |
| `PGPASSWORD` | `postgres` | warehouse password |
| `PGDATABASE` | `violence` | warehouse database |
| `ETL_SQLITE_PATH` | `data/warehouse/violence_staging.db` | staging/test SQLite file |
| `ETL_SOURCE_URL` | the Socrata export URL | download source |
| `ETL_LOG_LEVEL` | `INFO` | root log level |
| `ETL_DEDUP_MODE` | `drop` | `drop` or `sum` duplicate policy |
| `ETL_BRONZE_DIR` | `data/bronze` | landing/raw root |
| `DATABASE_URL` | unset | full URL override, takes precedence |

`DATABASE_URL` is honored verbatim when set; otherwise the URL is built from
`ETL_DB_BACKEND` and the PG or SQLite variables. The PostgreSQL dialect is
`postgresql+psycopg://` (psycopg 3).

## Usage

```
# Everything against SQLite, no PostgreSQL needed
python -m violence_etl.cli --backend sqlite init-db
python -m violence_etl.cli --backend sqlite run-all
python -m violence_etl.cli --backend sqlite validate

# Against the PostgreSQL warehouse
python -m violence_etl.cli init-db
python -m violence_etl.cli run-all
```

Commands:

- `init-db`: run `alembic upgrade head` for the configured backend.
- `download`: fetch the CSV to `data/bronze/landing` and print the sha256.
- `ingest-bronze [--csv-path PATH] [--force]`: bronze only.
- `build-silver [--sha SHA] [--force]`: silver only.
- `build-gold [--export-csv]`: gold only.
- `run-all [--csv-path PATH] [--force] [--export-csv]`: bronze, silver, gold.
- `validate`: print the acceptance checks.
- `drop-db --yes`: drop and recreate all tables (dev only).

Global flags, placed before the command: `--backend postgres|sqlite`,
`--sqlite-path PATH`, `--log-level LEVEL`.

Makefile aliases: `make install`, `make test`, `make lint`, `make init-db`,
`make run-all`, `make sqlite-run`.

## Layers

- Raw landing originals: `data/bronze/landing/<sha256>.csv` (verbatim bytes,
  never edited) plus a run-stamped copy in `data/bronze/raw/`.
- `bronze_crimes_raw`: every source field stored as text plus ingestion
  metadata (`source_url`, `source_file`, `source_sha256`, `load_ts`, `row_num`).
- `bronze_ingestion_log`: one row per successful load.
- `silver_crimes`: typed, trimmed, uppercased, code-preserving, deduplicated,
  validated, calendar-enriched rows.
- `silver_rejected_rows`: every rejected row with a reason and its raw values.
- `gold_*`: four denormalized tables, rebuilt by full refresh.

## Cleaning and deduplication

Silver applies, in order: strip whitespace; uppercase `departamento`,
`municipio` and `zona`; keep `cod_depto`/`cod_muni` as zero-padded text
(2 and 5 chars); parse `fecha_hecho` with the explicit `%d/%m/%Y` format;
cast `cantidad` to integer; restrict `zona` to `URBANA`/`RURAL`; reject null or
empty business fields; reject a `cod_depto` that is not the first two
characters of `cod_muni`; then deduplicate. Every rejected row is written to
`silver_rejected_rows` with a reason, so nothing is silently lost.

Deduplication is keyed on `(fecha_hecho, cod_depto, cod_muni, zona, cantidad)`,
because `departamento` and `municipio` are functionally dependent on the codes.

The default policy is `drop`, which keeps one row per business key. Repeated
identical rows are treated as ingestion duplication, not distinct events,
because the source has no event id and `CANTIDAD` is always 1. On the verified
dataset this removes 1,484 exact duplicates: 15,696 raw rows become 14,212
silver rows and the crime total goes from 15,696 to 14,212.

`ETL_DEDUP_MODE=sum` groups by the key without `cantidad` and sums `CANTIDAD`.
On this dataset it reproduces 15,696 as the crime total while still collapsing
to 14,212 rows. It is intended for datasets where `CANTIDAD` is a real
magnitude and duplicate rows are partial reports.

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

The full table 2003..2026 is asserted in `tests/test_periods.py`, so the mapper
cannot silently drift. Every year in the data range is classified.

## Gold tables

- `gold_top5_departments`: `rank` 1..5, ordered by `total_crimes DESC`, tie
  broken by `departamento ASC`.
- `gold_crimes_by_department`: all departments, total crimes.
- `gold_crimes_by_calendar`: grain `year x quarter x month x weekday`.
- `gold_crimes_by_electoral_period`: `period_order` uses the presentation order
  post, intermediate, pre, electoral; `pct_of_total` is the share of the grand
  total, rounded to 2 decimals.

Equivalent plain SQL:

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

## Tests

```
python -m pytest tests -q
python -m pytest tests -q --cov=violence_etl --cov-report=term-missing
python -m pytest tests/test_periods.py -q
```

The suite runs fully offline against SQLite using the committed fixtures. A
slow, network-backed test is skipped unless `ETL_FULL_DATASET=1` is set:

```
ETL_FULL_DATASET=1 python -m pytest tests -q -m full_dataset
```

## Notebooks

The notebooks under `notebooks/` are meant to be run from PyCharm using the IDE
Managed Jupyter server with the project `.venv` as the kernel. See
`notebooks/README.md` for details.

## Idempotency

The pipeline is safe to run repeatedly. Bronze is keyed on the content sha256
and re-downloading identical bytes is a no-op. Silver inserts use
`ON CONFLICT DO NOTHING` (PostgreSQL) or `INSERT OR IGNORE` (SQLite), so a
second load inserts zero rows. Gold is a full refresh. A second `run-all` on
the same source logs `skipped` at bronze and changes no row counts.
