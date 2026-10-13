# Violence on Elections ETL

Medallion (bronze/silver/gold) ETL for the Colombian electoral-violence
dataset published on datos.gov.co (Socrata view `yi5j-5fe9`).

The pipeline downloads the source CSV, lands it verbatim, mirrors it into a
bronze table, curates and deduplicates it into a silver table, and builds
small denormalized gold tables ready for SQL or BI queries.

The same codebase runs against PostgreSQL (warehouse) and SQLite
(staging/tests). The target is selected with `ETL_DB_BACKEND`.

See `docs/PLAN.md` for the full design.

## Quick start

```
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

# Run everything against SQLite (no PostgreSQL needed)
.venv/bin/python -m violence_etl.cli --backend sqlite init-db
.venv/bin/python -m violence_etl.cli --backend sqlite run-all

# Tests
.venv/bin/python -m pytest tests -q
```

Full usage guide is added in a later commit.
