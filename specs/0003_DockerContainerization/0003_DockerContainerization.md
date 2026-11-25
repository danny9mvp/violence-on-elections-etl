# 0003 DockerContainerization

## Summary and goals

Add container support for the Violence on Elections ETL so the same runtime image can be used for local DEV execution and for monthly run-to-completion execution as an Azure Container Apps Job. The focus is Dockerization (image, local compose workflow, and runtime/deployment expectations), not full Azure infrastructure provisioning.

Goals:
- Provide a runtime-only Docker image that runs the existing CLI and Alembic migrations without changing ETL business logic.
- Default the container to initialize the database schema and run all ETL phases in one execution.
- Support local DEV testing with SQLite and local artifact storage using mounted persistence.
- Document how the image is expected to run in PROD as a monthly Azure Container Apps Job using existing Key Vault, PostgreSQL, and Blob Storage integrations.

## Non-goals

- Full Azure Container Apps infrastructure provisioning, networking, identity assignment, registry setup, CI/CD publish automation, or Bicep/az deployment scripts.
- Changes to ETL transformation logic, database schema, or medallion semantics.
- Enabling `--export-csv` by default.
- Adding persistent volumes for PROD runs.
- Refactoring the existing Makefile, Python package layout, or dependency strategy beyond what is required for containerization.

## Existing behavior relevant to containerization

- Entry point: `python -m violence_etl.cli` (from repository root with `PYTHONPATH=src` in current local usage). Global flags `--sqlite-path` and `--log-level` apply before subcommands.
- Commands and flags: `init-db` runs `alembic upgrade head`; `run-all` executes bronze, silver, and gold with `--csv-path`, `--force`, and `--export-csv`; `validate` prints acceptance checks; `download`, `ingest-bronze`, `build-silver`, `build-gold`, and `drop-db --yes` are available for targeted or maintenance use.
- `src/violence_etl/cli.py` resolves `REPO_ROOT` from the package location and passes absolute `alembic.ini` and `migrations/` paths to Alembic. `alembic.ini` sets `script_location = migrations` and leaves `sqlalchemy.url` blank; `migrations/env.py` resolves the runtime URL from settings or Alembic config attributes. This requires `alembic.ini` and `migrations/` to be present in the image at paths consistent with the copied application layout.
- Settings and environment (`src/violence_etl/config/settings.py`): `ENV` defaults to `DEV` with valid values `DEV`, `TEST`, `PROD`; `ETL_SQLITE_PATH` defaults to `data/warehouse/violence_staging.db`; `ETL_BRONZE_DIR` defaults to `data/bronze`; `ETL_SOURCE_URL`, `ETL_LOG_LEVEL` (default `INFO`), and `ETL_DEDUP_MODE` (default `drop`) are supported. `ENV=PROD` requires `AZURE_KEYVAULT_URL`.
- DEV/TEST behavior: SQLite database and local artifact storage under `data/` paths (bronze landing/raw, optional gold CSV exports to `data/gold` or provided local export directory). `src/violence_etl/db/connection.py` creates the SQLite parent directory when needed.
- PROD behavior: PostgreSQL URL and blob storage configuration are resolved from Azure Key Vault using `DefaultAzureCredential`; database connection uses `sslmode=require`; bronze/gold CSV artifacts use Azure Blob Storage. Local `data/` artifact persistence is not the PROD storage path, so a data volume is redundant in PROD.
- Idempotency semantics: `init-db` applies migrations to head and is non-destructive/idempotent for existing schemas (it does not empty tables). Bronze reload is skipped for an already loaded content hash unless `--force` is set; silver/gold converge to the active snapshot on repeated runs. `drop-db --yes` is the destructive command that drops and recreates tables.
- Data source/network: without `--csv-path`, bronze ingest and `run-all` download from `ETL_SOURCE_URL` and require outbound network access. `--csv-path` allows reading a local input file while still persisting artifacts through the active storage backend.

## Requirements and constraints

### Runtime image

- Base image: `python:3.12-slim`, pinned to a specific 3.12 patch tag or digest during implementation for reproducible builds (the repository dependency markers target a wider range, but container runtime is standardized on Python 3.12).
- Runtime-only image: install runtime dependencies from `requirements.txt` only; do not install dev/test/notebook dependencies from `requirements-dev.txt`.
- Copy only files required to run the CLI and migrations: `src/`, `migrations/`, `alembic.ini`, and `requirements.txt` (plus any minimal packaging metadata only if required by the chosen install method; not expected for current `PYTHONPATH`/module execution).
- Set `PYTHONPATH=/app/src` and `PYTHONUNBUFFERED=1` in the image.
- Create application and data directories needed for local runs (for example `/app/data/warehouse`, `/app/data/bronze`, `/app/data/gold`) during image build.
- Run as a non-root user in the runtime image. File and directory ownership/permissions must allow Alembic execution and local DEV writes to the mounted/persisted data path.
- Default container command must execute `python -m violence_etl.cli init-db` and then `python -m violence_etl.cli run-all` (init-db followed by run-all). The command must allow override so operators can run other commands/arguments (for example `run-all --export-csv`, `validate`, `ingest-bronze --csv-path ...`).
- `--export-csv` remains off by default. It is enabled only when explicitly passed in command arguments.
- No secrets, credentials, `.env` files with real values, local datasets, SQLite databases, or local `data/` artifacts may be baked into the image.

### `.dockerignore`

- Add `.dockerignore` to reduce build context and prevent leaking or copying unnecessary content. It must exclude at minimum: `.git`, `.venv`, `venv`, `__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, coverage artifacts, local IDE/editor folders, `.env` and other secret-bearing files, local `data/` artifacts/databases/exports, notebooks/checkpoints if not required at runtime, and test caches/artifacts not needed in the runtime image.

### Local DEV compose workflow

- Provide `docker-compose.yml` for local DEV execution with `ENV=DEV` by default and local SQLite/local storage configuration.
- Compose must expose environment defaults/overrides relevant to local runs (at least `ENV`, `ETL_SQLITE_PATH`, `ETL_BRONZE_DIR`, `ETL_SOURCE_URL`, `ETL_LOG_LEVEL`, `ETL_DEDUP_MODE`) without embedding secrets.
- Mount persistent storage for local data (bind mount or named volume), for example `./data:/app/data`, so SQLite database and bronze/gold local artifacts persist across container runs.
- Compose must allow outbound network access for source download when `--csv-path` is not used.
- Compose must run the container as the same non-root runtime user strategy used by the image. Because Linux bind mounts can inherit host ownership that conflicts with a fixed container UID/GID, the design must document and support a safe permission strategy (for example named volume, configurable user mapping, or host-directory ownership guidance).

### ACA deployment assumptions (documentation-level)

- Target runtime in PROD is a monthly run-to-completion Azure Container Apps Job using the same image.
- PROD runs use `ENV=PROD` and `AZURE_KEYVAULT_URL`, rely on `DefaultAzureCredential`/managed identity for Key Vault and Blob access, and use Azure PostgreSQL and Azure Blob Storage as implemented today.
- No data volume is required or expected in PROD; local `ETL_SQLITE_PATH`/`ETL_BRONZE_DIR` persistence is a DEV/TEST concern.
- PROD configuration must fail fast on missing required Key Vault/configuration as existing behavior; missing secrets, auth failures, or unreachable dependencies should surface as job failure.

## Proposed design/approach

### Image layout

- Working directory: `/app`.
- Suggested layout in image:
  - `/app/requirements.txt`
  - `/app/alembic.ini`
  - `/app/migrations/...`
  - `/app/src/violence_etl/...`
  - `/app/data/` (created for local persistence mount point and default DEV paths)
- Environment:
  - `PYTHONPATH=/app/src`
  - `PYTHONUNBUFFERED=1`
- Build steps (conceptual): install OS/runtime prerequisites only if needed for wheels/connectivity already covered by current dependencies, upgrade packaging tools as appropriate, install `pip install --no-cache-dir -r requirements.txt`, copy runtime files, create data directories, create non-root user/group, set ownership for `/app` paths that must be writable, switch to non-root user.

### Entrypoint/CMD strategy

- Default behavior: run schema migration then full pipeline in one container execution.
- Recommended command form for default: shell command that chains both CLI invocations, for example `sh -c "python -m violence_etl.cli init-db && python -m violence_etl.cli run-all"`, so a successful container run always applies migrations before ETL and exits when the monthly run completes.
- Override behavior: replacing the container command/args must run the provided CLI command instead of the default chain. Documentation must include examples for:
  - default run: `init-db && run-all`
  - default with export: override to `sh -c "python -m violence_etl.cli init-db && python -m violence_etl.cli run-all --export-csv"` (or equivalent compose command override)
  - validation: `python -m violence_etl.cli validate`
  - targeted/local-input run: `python -m violence_etl.cli ingest-bronze --csv-path /app/data/input.csv` or a custom chain including `init-db` when needed
- Because overriding a chained default command replaces the whole chain, compose/ACA usage notes must be explicit that maintenance commands do not implicitly include `init-db` unless included in the override.

### docker-compose design (local DEV)

- Single service (for example `etl`) built from the repository Dockerfile.
- Default environment: `ENV=DEV`, `ETL_SQLITE_PATH=/app/data/warehouse/violence_staging.db`, `ETL_BRONZE_DIR=/app/data/bronze`, and pass-through/defaults for `ETL_SOURCE_URL`, `ETL_LOG_LEVEL`, `ETL_DEDUP_MODE`.
- Persistence: mount `./data:/app/data` as the documented default example; alternatively support a named volume for environments where host UID/GID mapping is inconvenient. The mounted path must cover both SQLite and local bronze/gold artifacts.
- Network: default bridge/network access sufficient for outbound HTTPS/HTTP to `ETL_SOURCE_URL`.
- User/permissions: run as non-root by default. For bind mounts on Linux, either pre-create/chown the host `./data` directory to the container user mapping, make the compose user configurable, or prefer a named volume. This must be documented to avoid permission errors on first run.
- Usage patterns:
  - `docker compose run --rm etl` executes default `init-db && run-all`.
  - `docker compose run --rm etl python -m violence_etl.cli validate` runs validation against persisted local data.
  - `docker compose run --rm etl sh -c "python -m violence_etl.cli init-db && python -m violence_etl.cli run-all --export-csv"` enables gold CSV export locally.

### ACA Container Apps Job notes (PROD)

- Run as a scheduled/manual job configured for run-to-completion (single execution per monthly trigger), not as a continuously running app/service.
- Image command uses the same default (`init-db && run-all`) unless an explicit operational override is required.
- Required environment/config: `ENV=PROD`, `AZURE_KEYVAULT_URL`, and any non-secret runtime tuning values if needed (for example `ETL_LOG_LEVEL`, `ETL_SOURCE_URL`). Database and blob secrets/config are fetched from Key Vault by existing application logic.
- Identity and access: job identity must work with `DefaultAzureCredential` and have permissions/network access to Key Vault, Azure PostgreSQL, and Azure Blob Storage.
- No mounted data volume. Any artifact persistence in PROD is handled by existing Blob Storage integration; container filesystem is ephemeral.
- Observability/operations: rely on container stdout/stderr logs and non-zero exit codes for job failure detection; `validate` can be run as an ad hoc override in a controlled environment if needed.

## Acceptance criteria

- A Docker image can be built from the repository using `python:3.12-slim` and runtime dependencies only.
- The image contains `src/`, `migrations/`, and `alembic.ini`, sets `PYTHONPATH=/app/src` and `PYTHONUNBUFFERED=1`, and runs as a non-root user.
- Running the image with default command performs `init-db` and then `run-all`; `--export-csv` is not used unless explicitly requested.
- Command/argument override works for running alternate CLI operations (for example `validate` or `run-all --export-csv`).
- `docker-compose.yml` supports local DEV with `ENV=DEV`, SQLite/local storage, outbound network access, and mounted persistence (bind or named volume) such that rerunning the pipeline is idempotent and preserves local data across runs.
- `.dockerignore` prevents common VCS/venv/cache/secret/local-data artifacts from entering the build context/image.
- Documentation describes local DEV usage, non-root mount permission considerations, and ACA job expectations for PROD without requiring a data volume.
- No secrets or local data artifacts are baked into the image.
- PROD runtime expectations remain consistent with existing behavior: Azure Key Vault/PostgreSQL/Blob Storage integrations, `DefaultAzureCredential`, fail-fast on missing required PROD configuration, and no dependency on a local persistent volume.

## Testing and validation plan

Build and static checks:
- Build the image locally (for example `docker build -t violence-etl:dev .`) and confirm it completes using runtime dependencies only.
- Inspect image configuration to verify default command, `PYTHONPATH`, `PYTHONUNBUFFERED`, working directory, and non-root user.
- Confirm `.dockerignore` excludes `.git`, virtual environments, caches, `.env` files, and local `data/` contents from the build context.

Local DEV functional checks (compose):
- Start/run with compose in `ENV=DEV` using mounted persistence and outbound network access.
- Verify first run executes migrations and completes `run-all` successfully, creating/updating the SQLite database and local bronze artifacts under the mounted data path.
- Run the container again with the same mounted data and confirm idempotent behavior (no unintended duplicate growth; bronze reload semantics and silver/gold convergence match existing behavior).
- Run `validate` in a follow-up container using the same persisted data and confirm it reports expected checks for the loaded snapshot.
- Run an override with `--export-csv` and confirm gold CSV files are written to the local persisted export location.
- If feasible, test `--csv-path` with a mounted local input file to confirm offline/local-input execution path.

Safety and regression checks:
- Verify no secrets or local artifacts are present in image layers (basic image/filesystem inspection).
- Verify non-root execution can write to the configured data mount strategy; document or adjust compose guidance if bind-mount permissions fail on Linux.
- Confirm existing application behavior is unchanged outside container packaging (no source logic modifications in this feature).

PROD-oriented validation (documentation/expectation checks):
- Validate that container configuration for PROD can set `ENV=PROD` and `AZURE_KEYVAULT_URL` without a data volume.
- Confirm implementation preserves existing fail-fast behavior when required PROD configuration/secrets are unavailable (to be observed in an environment with Azure access during deployment validation, not as part of local offline tests).
- Confirm ACA job run-to-completion assumptions are documented (scheduled monthly execution, exit-code based success/failure, no persistent volume).

## Risks and edge cases

- Non-root bind-mount permissions on Linux: host-owned `./data` directories may not be writable by the container user, causing migration or ETL write failures. Compose guidance must cover ownership, user mapping, or named-volume alternatives.
- Alembic and path resolution: incorrect working directory, missing `alembic.ini`/`migrations/`, or missing `PYTHONPATH` can break `init-db` and default startup even though `REPO_ROOT` is derived from package location.
- Outbound network/download dependency: default runs without `--csv-path` require access to `ETL_SOURCE_URL`; restricted networks will fail during bronze download unless a local CSV path is provided.
- First-run initialization: the default chained command depends on `init-db` succeeding before `run-all`; override commands that skip `init-db` against an uninitialized database will fail.
- Ephemeral container filesystem: without a mounted volume in local DEV, SQLite and local artifacts are lost on container removal; this is expected but must be clearly documented.
- Python 3.12 compatibility: runtime is pinned to Python 3.12 for containers, while project markers claim Python 3.8-3.14 with limited local execution history outside the currently tested interpreter; dependency resolution or behavior differences should be validated during image build and local container runs.
- Azure runtime dependencies: Key Vault, PostgreSQL, and Blob access in PROD depend on Azure SDK/runtime authentication and network reachability; containerization does not remove these external prerequisites.

## Assumptions and documentation updates

Assumptions:
- The container image is built from the repository root with access to `src/`, `migrations/`, `alembic.ini`, and dependency manifests.
- `init-db` followed by `run-all` is an acceptable default for both local DEV convenience and monthly PROD job execution because migrations are idempotent and `init-db` is non-destructive.
- Local DEV persistence uses a mounted path under `/app/data`; named volumes are acceptable where bind-mount permissions are problematic.
- ACA-specific scheduling, registry publishing, identity wiring, and secret injection mechanisms are handled outside this repository and only need runtime expectations documented here.

Documentation updates needed:
- `README.md`: add Docker build/run instructions, default command behavior, override examples (`run-all --export-csv`, `validate`), local compose usage with mounted persistence, and notes that local `data/` persistence applies to DEV/TEST while PROD uses Azure services without a data volume.
- `.env.example` or Docker-specific env example documentation: clarify container-relevant variables and that secrets must be provided at runtime (not baked into images), with `AZURE_KEYVAULT_URL` required for PROD.
- `docs/PLAN.md` (if maintained for deployment/runtime architecture): note containerized execution model, DEV local volume usage, and ACA monthly job run-to-completion assumption.
- `specs/INDEX.md`: add feature `0003 DockerContainerization`.
