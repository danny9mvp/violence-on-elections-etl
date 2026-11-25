# 0004 GitHub Actions Integration

## Summary and goals

Add GitHub Actions workflows for continuous integration and controlled Docker image publishing for the Violence on Elections ETL. The feature standardizes lint/static analysis, tests with coverage enforcement, and deterministic pipeline validation on pull requests and protected branches, and publishes a Docker Hub image only after successful validation on merges to `main`.

Goals:

- Add CI workflows triggered for `develop`, `main`, `feat/**`, and `hotfix/**` branches, and for pull requests targeting `develop` and `main`.
- Use `ruff` as the static code analysis/lint gate for the current Python scope.
- Enforce a minimum 80% test coverage threshold and produce coverage artifacts (`coverage.xml` and terminal summary).
- Add deterministic pipeline validation using the committed fixture `tests/fixtures/yi5j-5fe9_sample.csv`, SQLite/local storage, `init-db`, `run-all --csv-path ...`, and `validate`, with no external download by default.
- Build and push the Docker image to Docker Hub only on `push` to `main` after required validation passes, using GitHub Secrets for credentials.
- Update the Makefile so CI can use stable targets with Python/PYTHONPATH overrides and deterministic validation helpers.

## Non-goals

- Changing ETL business logic, schema, medallion semantics, or data contracts.
- Adding CodeQL, bandit, SAST beyond `ruff`, dependency scanning, or security platform integrations.
- Provisioning GitHub branch protection/rulesets, Docker Hub repositories, Azure infrastructure, or secrets in external systems; the spec documents required configuration.
- Publishing images on pull requests, feature branches, `develop`, tags, or release events beyond the confirmed `push` to `main` rule.
- Publishing non-semver image tags, including `:latest`.
- Introducing a matrix across all supported Python versions unless explicitly added later; CI standardizes on a practical runtime for this feature.
- Refactoring package layout or replacing the `src/` + `PYTHONPATH` model outside minimal Makefile/CI support.

## Existing behavior and constraints

- Current branch context: repository uses `develop` as the active integration branch and `main` exists on origin. Feature branches in this repo use `feat/**` (equivalent to `feature/**`); this feature includes `feat/**` and `hotfix/**` as confirmed.
- Package layout: application code lives under `src/violence_etl/`. Local CLI and tests commonly require `PYTHONPATH=src` (see `README.md`, `docs/PLAN.md` TODO 4/5). CI commands and Makefile targets must account for this.
- Makefile currently sets `PYTHON ?= .venv/bin/python` and `CLI = $(PYTHON) -m violence_etl.cli`, has no `test-cov` or deterministic CI pipeline target, and `drop-db` uses spaces instead of a tab recipe. `lint` runs `$(PYTHON) -m ruff check .`.
- Dev dependencies already include `pytest`, `ruff`, `pytest-cov`, and `coverage` in `requirements-dev.txt`.
- Existing tests use SQLite and fixtures; `tests/fixtures/yi5j-5fe9_sample.csv` is committed and deterministic. `tests/test_pipeline_sqlite.py` and CLI tests demonstrate local SQLite runs with `ENV=TEST` and `--csv-path`.
- CLI behavior relevant to CI validation: `init-db` runs Alembic migrations; `run-all` accepts `--csv-path`, `--force`, and `--export-csv`; `validate` returns exit code `0` on PASS and `1` on FAIL. Validation should run against a clean temporary SQLite DB and bronze directory with `ENV=TEST`.
- Lint debt: `docs/PLAN.md` TODO 6 records that `make lint` reports 28 existing ruff errors, mostly unsorted imports. Enforcing lint as a required check will block PRs until this debt is resolved.
- Docker image behavior: Dockerfile builds a runtime-only image (`python:3.12.12-slim`, non-root, `PYTHONPATH=/app/src`) and defaults to `init-db && run-all`. CI image publishing must not change runtime defaults.
- GitHub workflow constraints: workflow success/failure alone does not block merges. PR merge blocking requires GitHub branch protection/rulesets that require status checks. Branch protection configuration is outside workflow files and must be documented as an operational requirement.
- Security constraint: no secrets, tokens, credentials, or `.env` values may be committed. Docker Hub credentials must be stored only in GitHub Secrets/variables as configured; no secret values may be recorded in repository artifacts.

## Requirements

### R1. Workflow triggers and branch scope

- CI workflow runs on:
  - `push` to `develop`, `main`, `feat/**`, and `hotfix/**`.
  - `pull_request` targeting `develop` and `main`.
- Docker publish workflow/job runs only on `push` to `main` and only after required validation jobs succeed.
- The spec treats `feat/**` as the repository's feature branch pattern; `feature/**` may be mentioned as equivalent in documentation, but `feat/**` is the required configured pattern.

### R2. Static code analysis

- Use `ruff` as the static analysis/lint tool for current Python scope.
- CI runs `ruff check .` (or equivalent Makefile target) as a required quality gate.
- No CodeQL/bandit is required in this feature.

### R3. Tests and coverage

- CI runs the automated test suite with pytest.
- Coverage is enforced at minimum 80% using `--cov-fail-under=80`.
- Coverage outputs include terminal summary (`term-missing` or equivalent) and `coverage.xml`.
- `coverage.xml` is uploaded as a workflow artifact for inspection/download.

### R4. Deterministic pipeline validation

- CI runs deterministic ETL validation with no external download by default.
- Validation uses committed fixture `tests/fixtures/yi5j-5fe9_sample.csv`.
- Validation uses SQLite/local storage in an isolated temporary location per run (for example `${{ runner.temp }}`), with `ENV=TEST`.
- Validation executes, in order, against the clean temp environment:
  1. `init-db`
  2. `run-all --csv-path tests/fixtures/yi5j-5fe9_sample.csv`
  3. `validate`
- The `validate` command must exit non-zero on FAIL; CI treats non-zero as failure.

### R5. Docker Hub publishing

- Publish only on `push` to `main` (post-merge), after required validation passes.
- Use Docker Hub credentials/configuration from GitHub repository settings: secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, and variable `DOCKERHUB_REPOSITORY`. The user confirmed these entries were created in GitHub repository settings; this spec records names only, never values.
- Do not write secret values into workflow files, spec, docs, logs, or committed files.
- Image repository is configured via `DOCKERHUB_REPOSITORY` and must resolve to the target Docker Hub repository name (for example `owner/image`). Publish must fail fast with a clear error if `DOCKERHUB_REPOSITORY` is missing or empty.
- Image tag strategy is semver-only: publish `DOCKERHUB_REPOSITORY:<semver>`. Do not publish `:latest` or any non-semver tag.
- Semver source of truth is `pyproject.toml` `[project].version`. Implementation must add `[project].version` if missing. Publish must fail if `[project].version` is missing, empty, or not a valid semantic version.

### R6. Makefile updates for CI

- Makefile remains in scope and CI should use Makefile targets where practical.
- `PYTHON` must be override-friendly for CI (CI uses `python`, local default may remain `.venv/bin/python`).
- `PYTHONPATH=src` handling must be explicit and consistent for CLI/test/lint targets used by CI.
- Add `test-cov` target: pytest with coverage and `--cov-fail-under=80`, producing terminal summary and `coverage.xml`.
- Add deterministic pipeline validation target (for example `ci-validate` or `validate-fixture`) using fixture CSV and clean temp paths/ENV.
- Ensure lint target is usable in CI.
- Fix `drop-db` recipe tab indentation.

### R7. Documentation and operational configuration

- Document required GitHub Secrets/variables, workflow behavior, branch protection/ruleset expectations, and local reproduction commands.
- Document that branch protection/rulesets requiring status checks are required to block merges; workflow failures alone are insufficient.

## Assumptions

- GitHub Actions is enabled for the repository and runners have outbound internet access for dependency installation and Docker base image pulls.
- GitHub repository settings already contain `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, and `DOCKERHUB_REPOSITORY`, as confirmed by the user. The spec does not include or assume any secret/variable values.
- The Docker Hub repository exists or will be created by the maintainer; credentials have push permission.
- Python 3.12 is the CI runtime baseline for this feature because the Docker image is pinned to `python:3.12.12-slim` and the project already supports 3.12.
- `pyproject.toml` `[project].version` is the semver source of truth. If missing during implementation, it must be added; publish must fail when missing/invalid.
- Branch protection/rulesets will be configured by a repository maintainer with appropriate permissions; workflow files cannot enforce them alone.

## Proposed design and approach

### Workflow structure

Use two workflows under `.github/workflows/`:

1. `ci.yml` (name: `CI`): lint, tests/coverage, and deterministic pipeline validation.
2. `docker-publish.yml` (name: `Docker Publish`) or a `publish` job in a workflow triggered only by `push` to `main` with dependency on validation jobs. A separate workflow is preferred for clarity, but it must not publish unless equivalent required validation has passed for the same commit/SHA on `main`.

Recommended approach: keep validation in `ci.yml` and have `docker-publish.yml` trigger on `push` to `main` and call/reuse the same validation logic through a reusable workflow (`workflow_call`) or duplicate only by referencing shared Makefile targets after an explicit dependency pattern. Simpler acceptable design: single workflow with `ci` jobs on PR/push triggers and `publish` job with `needs: [lint, test, pipeline-validate]`, `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`. The spec allows either, but the implementation must make the "publish only after required validation passes" rule unambiguous.

### Triggers

`ci.yml`:

```yaml
on:
  push:
    branches:
      - develop
      - main
      - 'feat/**'
      - 'hotfix/**'
  pull_request:
    branches:
      - develop
      - main
```

Publish trigger:

```yaml
on:
  push:
    branches:
      - main
```

No `pull_request` trigger for image push. No feature/hotfix/develop image push.

### Jobs and commands

#### Job: `lint`

- Runner: `ubuntu-latest`.
- Python: `3.12`.
- Steps: checkout, setup-python, install dev dependencies, run lint.
- Preferred command: `make lint PYTHON=python`.
- Gate: `ruff check .` must pass.

#### Job: `test`

- Runner: `ubuntu-latest`.
- Python: `3.12`.
- Install: `python -m pip install --upgrade pip` and `python -m pip install -r requirements-dev.txt`.
- Preferred command: `make test-cov PYTHON=python`.
- Expected test-cov behavior: `PYTHONPATH=src python -m pytest tests -q --cov=violence_etl --cov-report=term-missing --cov-report=xml --cov-fail-under=80`.
- Upload `coverage.xml` as artifact (for example `coverage-xml`).

#### Job: `pipeline-validate`

- Runner: `ubuntu-latest`.
- Python: `3.12`.
- Uses clean temp paths per run; does not write persistent repo data artifacts.
- Preferred command: `make ci-validate PYTHON=python`.
- Target behavior (conceptual):

```sh
TMP_ROOT="${RUNNER_TEMP:-/tmp}/violence-etl-ci"
DB_PATH="$TMP_ROOT/warehouse/violence_ci.db"
BRONZE_DIR="$TMP_ROOT/bronze"
rm -rf "$TMP_ROOT" && mkdir -p "$TMP_ROOT"
PYTHONPATH=src ENV=TEST ETL_SQLITE_PATH="$DB_PATH" ETL_BRONZE_DIR="$BRONZE_DIR" \
  python -m violence_etl.cli init-db
PYTHONPATH=src ENV=TEST ETL_SQLITE_PATH="$DB_PATH" ETL_BRONZE_DIR="$BRONZE_DIR" \
  python -m violence_etl.cli run-all --csv-path tests/fixtures/yi5j-5fe9_sample.csv
PYTHONPATH=src ENV=TEST ETL_SQLITE_PATH="$DB_PATH" ETL_BRONZE_DIR="$BRONZE_DIR" \
  python -m violence_etl.cli validate
```

- No external download: `--csv-path` is mandatory in this target.
- `validate` non-zero exit fails the job.

#### Job: `docker-publish`

- Condition: only `push` to `main`.
- Depends on: `lint`, `test`, `pipeline-validate` all successful.
- Steps: checkout, setup Docker Buildx, login to Docker Hub using secrets, compute semver tag, build and push.
- Docker Hub login: `docker/login-action` with `username: ${{ secrets.DOCKERHUB_USERNAME }}` and `password: ${{ secrets.DOCKERHUB_TOKEN }}`.
- Image repository: `${{ vars.DOCKERHUB_REPOSITORY }}`. The workflow must fail fast with a clear error if the variable is missing or empty; no fallback repository name is used.
- Tag strategy: push exactly one image tag, `:${SEMVER}`, where `SEMVER` comes from `pyproject.toml` `[project].version`. Validate the value as semantic versioning before publishing; fail if missing/invalid. Do not derive semver from commit SHA and do not publish `:latest`.
- Push occurs only after build and required checks pass. Use `docker/build-push-action` with `push: true` only in this job.

### Makefile changes

Proposed Makefile adjustments (implementation detail may vary slightly, but requirements must hold):

- Keep default local Python: `PYTHON ?= .venv/bin/python`.
- Add `PYTHONPATH`/CLI helpers:

```make
PYTHON ?= .venv/bin/python
PYTHONPATH ?= src
CLI = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m violence_etl.cli
PYTEST = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest
RUFF = $(PYTHON) -m ruff
```

- `lint`: `$(RUFF) check .` (usable in CI with `make lint PYTHON=python`).
- `test`: `$(PYTEST) tests -q`.
- `test-cov`: `$(PYTEST) tests -q --cov=violence_etl --cov-report=term-missing --cov-report=xml --cov-fail-under=80`.
- `ci-validate`: deterministic fixture validation using temp paths. It should accept overridable variables like `CI_TMP_DIR`, `CI_DB_PATH`, `CI_BRONZE_DIR`, and `FIXTURE_CSV ?= tests/fixtures/yi5j-5fe9_sample.csv`; default temp root should be safe (`${TMPDIR:-/tmp}/violence-etl-ci` or equivalent). The target must clean/create its temp area and run init-db, run-all with fixture csv, validate with `ENV=TEST`.
- Fix `drop-db` indentation to a tab.
- Optionally include `ci` aggregate target (`lint test-cov ci-validate`) for local parity; workflow may call individual targets for clearer job reporting.

### Branch protection and required checks

Workflow files do not configure GitHub branch protection/rulesets. Repository maintainers must configure branch protection or repository rulesets so merges to `develop` and `main` require passing status checks. Recommended required checks:

- `CI / lint` (or workflow/job name chosen)
- `CI / test`
- `CI / pipeline-validate`

If names differ in implementation, documentation must list the exact check names. Pull request checks target `develop` and `main` by workflow trigger; merge blocking is enforced by branch protection/rulesets.

### Secrets and variables

Required GitHub Secrets (names only; user confirmed created in repository settings):

- `DOCKERHUB_USERNAME`: Docker Hub username.
- `DOCKERHUB_TOKEN`: Docker Hub access token/PAT with push permission.

Required GitHub repository variable (name only; user confirmed created in repository settings):

- `DOCKERHUB_REPOSITORY`: Docker Hub image repository name, e.g. `owner/image`. Required for publish; workflow fails fast if missing/empty.

No Azure secrets are needed for this CI feature because deterministic validation uses SQLite/local fixture data.

## Implementation tasks and steps

1. **Branch and baseline**
   - Create/switch to `feat/github-actions-integration` from `origin/develop`.
   - Confirm no unrelated files are modified by this feature.

2. **Resolve lint gate rollout**
   - Run `ruff check .` and fix the existing lint debt (currently 28 errors, mostly unsorted imports per `docs/PLAN.md` TODO 6), or otherwise align configuration only if justified and documented. Preferred path: fix debt in this feature so lint can be a required check.
   - Update `docs/PLAN.md` TODO 6 status/notes if resolved.

3. **Makefile updates**
   - Make `PYTHON` override-friendly; add `PYTHONPATH=src` support for CLI/test targets.
   - Add `test-cov` target with `--cov-fail-under=80` and `coverage.xml`.
   - Add deterministic `ci-validate`/`validate-fixture` target using `tests/fixtures/yi5j-5fe9_sample.csv`, `ENV=TEST`, clean temp SQLite DB and bronze dir.
   - Fix `drop-db` recipe tab indentation.
   - Keep existing local developer workflows working.

4. **GitHub Actions CI workflow**
   - Add `.github/workflows/ci.yml` with push/PR triggers for required branches.
   - Implement `lint`, `test`, and `pipeline-validate` jobs using Makefile targets where practical.
   - Upload `coverage.xml` artifact.
   - Ensure workflow uses `python` (not `.venv/bin/python`) and installs `requirements-dev.txt`.

5. **Docker publish workflow/job**
   - Add publish logic for `push` to `main` only, dependent on validation jobs.
   - Configure Docker Hub login using `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets.
   - Resolve image repository from required GitHub variable `DOCKERHUB_REPOSITORY`; fail fast if missing/empty.
   - Implement semver tag resolution from `pyproject.toml` `[project].version`; add version during implementation if missing and fail publish when missing/invalid.
   - Push only `DOCKERHUB_REPOSITORY:<semver>`; do not publish `:latest`.
   - Ensure no publish on PRs/feature/hotfix/develop.

6. **Documentation**
   - Update `README.md` with CI/CD behavior, Makefile targets, local reproduction commands, required secrets/variables, and branch protection note.
   - Update `.env.example` only if needed for CI-related local vars (not expected). Do not add secrets.
   - Update `docs/PLAN.md` for CI/CD and Makefile/lint-debt status as appropriate.
   - Update `specs/INDEX.md` with feature 0004.

7. **Validation**
   - Run Makefile/CLI commands locally: lint, test-cov, deterministic fixture validation.
   - Optionally run `docker build` smoke check if feasible.
   - Verify workflow YAML syntax and paths.

## Testing and validation plan

### Local/CI command validation

- Lint: `make lint PYTHON=python` (or equivalent) passes with no ruff errors.
- Tests + coverage: `make test-cov PYTHON=python` passes, enforces `--cov-fail-under=80`, prints terminal coverage summary, and generates `coverage.xml`.
- Deterministic pipeline validation: `make ci-validate PYTHON=python` (or chosen name) passes using `tests/fixtures/yi5j-5fe9_sample.csv`, clean temp SQLite DB, clean temp bronze dir, and `ENV=TEST`.
- Validate failure behavior: confirm `validate` returns non-zero on FAIL and CI job fails when validation fails (can be exercised by a negative local smoke test against an empty/bad temp DB outside committed tests if needed).

### Workflow validation

- Confirm `ci.yml` triggers on push to `develop`, `main`, `feat/**`, `hotfix/**` and pull_request to `develop`, `main`.
- Confirm publish runs only on push to `main` and has `needs`/dependency on required validation jobs.
- Confirm publish job uses secrets and does not expose token values.
- Confirm coverage artifact upload includes `coverage.xml`.

### Acceptance checks

- PRs to `develop`/`main` run lint, tests+coverage, and deterministic pipeline validation.
- Coverage below 80% fails CI.
- Ruff violations fail CI.
- Pipeline validation uses fixture CSV and no external download by default.
- Docker image is pushed to Docker Hub only for `main` pushes after successful validation, tagged only as `DOCKERHUB_REPOSITORY:<semver>` from `pyproject.toml` `[project].version`; no `:latest` tag.
- No secrets are committed.

## Risks, edge cases, and rollout

- **Lint debt blocks CI**: existing 28 ruff errors will fail the lint gate. Rollout plan: fix lint debt as part of 0004 before making lint required, or land lint fixes in the same change series and enable required status checks only after green. Preferred: fix in 0004 and gate immediately.
- **Coverage threshold instability**: adding tests or excluding generated paths incorrectly can cause brittle coverage. Keep coverage scope focused on `violence_etl` package and avoid excluding production code just to pass threshold.
- **`src/` layout import failures in CI**: missing `PYTHONPATH=src` causes module resolution/import errors. Mitigate with Makefile variables and explicit CI commands.
- **Temp path collisions/dirty state**: pipeline validation must use unique/clean temp dirs and avoid writing into repo `data/`.
- **Validate false positives if DB not clean**: stale SQLite DB can mask failures. Mitigate by deleting/recreating temp DB and bronze dir before run.
- **Docker publish on wrong event**: misconfigured trigger could push images from PRs/branches. Mitigate with explicit `if` condition on `push` to `main`, no PR trigger, and semver-only tagging.
- **Semver source ambiguity**: inconsistent tags are avoided by making `pyproject.toml` `[project].version` the single source of truth and failing publish when missing/invalid.
- **Branch protection not configured**: workflows may pass/fail but merges still possible. Mitigate by documenting required branch protection/rulesets and check names; maintainer must configure them in GitHub settings.
- **Docker Hub config misconfiguration**: missing/invalid secrets or `DOCKERHUB_REPOSITORY` causes publish failure on main. Mitigate with clear preflight documentation and fail-fast checks that do not print secret values.
- **External dependency flakiness**: dependency install or Docker base pulls can fail transiently. Mitigate with pinned action versions, pip cache where safe, and clear job logs.

## Documentation updates

- `README.md`: add "CI/CD" section describing workflows, triggers, required checks, Makefile targets, local reproduction commands, coverage artifact, deterministic fixture validation, Docker Hub publish rules, semver source (`pyproject.toml` `[project].version`), and secret/variable names (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `DOCKERHUB_REPOSITORY`) without values.
- `docs/PLAN.md`: update TODO 6 lint debt status and add CI/GitHub Actions notes; record Makefile CI target additions and the resolved semver/version source decision.
- `.env.example`: no secrets; update only if new non-secret CI/local variables are introduced (unlikely).
- `specs/INDEX.md`: add feature 0004 entry.
- Operational docs in spec/README must state: merge blocking requires GitHub branch protection/rulesets requiring status checks; workflow failures alone are insufficient.

## Decisions (resolved)

- **Semver source of truth**: `pyproject.toml` `[project].version` is the single source of truth for `DOCKERHUB_REPOSITORY:<semver>`. Implementation must add `[project].version` if missing. Publish must fail if the version is missing, empty, or invalid semver.
- **Docker Hub repository configuration**: `DOCKERHUB_REPOSITORY` is required and must come from the GitHub repository variable of that name. The user confirmed `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, and `DOCKERHUB_REPOSITORY` exist in GitHub repository settings. No fallback/default repository name is used; publish fails fast if `DOCKERHUB_REPOSITORY` is missing/empty.
- **Tag policy**: semver-only. Publish `DOCKERHUB_REPOSITORY:<semver>` and do not publish `:latest` or any other tag.

## Implementation notes for Makefile target shape

The following is an illustrative shape; implementation may adjust names/variables while preserving requirements.

```make
PYTHON ?= .venv/bin/python
PYTHONPATH ?= src
CLI = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m violence_etl.cli
PYTEST = PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest
RUFF = $(PYTHON) -m ruff
FIXTURE_CSV ?= tests/fixtures/yi5j-5fe9_sample.csv
CI_TMP_DIR ?= $(TMPDIR:/=)/violence-etl-ci
CI_DB_PATH ?= $(CI_TMP_DIR)/warehouse/violence_ci.db
CI_BRONZE_DIR ?= $(CI_TMP_DIR)/bronze

.PHONY: install test test-cov lint init-db drop-db run-all sqlite-run ci-validate

lint:
	$(RUFF) check .

test:
	$(PYTEST) tests -q

test-cov:
	$(PYTEST) tests -q --cov=violence_etl --cov-report=term-missing --cov-report=xml --cov-fail-under=80

drop-db:
	$(CLI) drop-db

ci-validate:
	rm -rf "$(CI_TMP_DIR)"
	mkdir -p "$(CI_TMP_DIR)/warehouse" "$(CI_BRONZE_DIR)"
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) init-db
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) run-all --csv-path "$(FIXTURE_CSV)"
	ENV=TEST ETL_SQLITE_PATH="$(CI_DB_PATH)" ETL_BRONZE_DIR="$(CI_BRONZE_DIR)" $(CLI) validate
```

Notes:

- CI should invoke targets as `make lint PYTHON=python`, `make test-cov PYTHON=python`, `make ci-validate PYTHON=python`.
- The `ci-validate` target must not download external data; it always passes `--csv-path` with the committed fixture.
- If `TMPDIR` behavior varies across environments, implementation should pick a portable default and document it.
