PYTHON ?= .venv/bin/python
PYTHONPATH ?= src
CLI = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m violence_etl.cli
PYTEST = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest
RUFF = $(PYTHON) -m ruff
FIXTURE_CSV ?= tests/fixtures/yi5j-5fe9_sample.csv
CI_TMP_DIR ?= $(or $(TMPDIR),/tmp)/violence-etl-ci
CI_DB_PATH ?= $(CI_TMP_DIR)/warehouse/violence_ci.db
CI_BRONZE_DIR ?= $(CI_TMP_DIR)/bronze

.PHONY: install test test-cov lint init-db drop-db run-all sqlite-run ci-validate

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTEST) tests -q

test-cov:
	$(PYTEST) tests -q --cov=violence_etl --cov-report=term-missing --cov-report=xml --cov-fail-under=80

lint:
	$(RUFF) check .

init-db:
	$(CLI) init-db

drop-db:
	$(CLI) drop-db

run-all:
	$(CLI) run-all

sqlite-run:
	ENV=DEV ETL_SQLITE_PATH=data/warehouse/violence_staging.db $(CLI) init-db
	ENV=DEV ETL_SQLITE_PATH=data/warehouse/violence_staging.db $(CLI) run-all

ci-validate:
	rm -rf "$(CI_TMP_DIR)"
	mkdir -p "$(CI_TMP_DIR)/warehouse" "$(CI_BRONZE_DIR)"
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) init-db
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) run-all --csv-path "$(FIXTURE_CSV)"
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) validate
