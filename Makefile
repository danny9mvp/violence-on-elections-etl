PYTHON ?= .venv/bin/python
CLI = $(PYTHON) -m violence_etl.cli

.PHONY: install test lint init-db run-all sqlite-run

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest tests -q

lint:
	$(PYTHON) -m ruff check .

init-db:
	$(CLI) init-db

drop-db:
    $(CLI) drop-db

run-all:
	$(CLI) run-all

sqlite-run:
	ENV=DEV ETL_SQLITE_PATH=data/warehouse/violence_staging.db $(CLI) init-db
	ENV=DEV ETL_SQLITE_PATH=data/warehouse/violence_staging.db $(CLI) run-all
