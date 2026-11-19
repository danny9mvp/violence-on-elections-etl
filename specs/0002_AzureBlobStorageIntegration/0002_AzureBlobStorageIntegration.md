# 0002 AzureBlobStorageIntegration

## Summary and goals

Add Azure Blob Storage support for CSV artifact persistence in production. In `ENV=PROD`, bronze and gold CSV artifacts are read from and written to Azure Blob Storage containers whose names and storage account are resolved from Azure Key Vault. In `ENV=DEV` and `ENV=TEST`, all file reads and writes keep using the local `data/` directory with current behavior unchanged.

Goals:
- Retrieve `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER` from Key Vault in `PROD` using the existing generic `KeyVaultClient`.
- Use those values to connect to Azure Blob Storage for bronze and gold CSV artifacts.
- Keep pipeline, transformation, and CLI behavior logically unchanged while abstracting artifact storage by environment.
- Keep `KeyVaultClient` generic and free of blob, database, or secret-name-specific logic.

## Existing behavior (relevant)

- `specs/INDEX.md` lists feature `0001 KeyVaultIntegration`. This feature is `0002`.
- `src/violence_etl/clients/key_vault.py` provides generic `KeyVaultClient(vault_url, credential=None, secret_client=None)` with lazy Azure imports and `get_secret(name)`.
- `src/violence_etl/config/settings.py` defines `Settings` (`env`, `sqlite_path`, `source_url`, `log_level`, `dedup_mode`, `bronze_dir`, `key_vault_url`, `blob_storage`) and `get_settings()`. In `PROD`, `AZURE_KEYVAULT_URL` is required and `get_settings()` eagerly resolves blob storage configuration. `database_url_object()` returns SQLite for `DEV`/`TEST` and calls `postgres_url_from_key_vault()` for `PROD`.
- `src/violence_etl/utils/io.py` handles source download and local file helpers: `download_source()` returns bytes; `landing_path()`, `write_landing()`, `write_run_raw_copy()`, `read_csv()`, `sha256_file()`, and `file_sha_or_none()` operate on local paths with current pandas/hash behavior.
- `src/violence_etl/transformations/bronze.py` downloads or reads input bytes, persists run/raw and landing artifacts through the selected artifact storage service, reads the landing CSV for ingestion, validates the header, and records `source_file` and `source_sha256`. It supports `csv_path` for a local input override.
- `src/violence_etl/transformations/gold.py` builds aggregates in the database and, when export is requested, exports four CSVs through the selected artifact storage service: `gold_top5_departments.csv`, `gold_crimes_by_department.csv`, `gold_crimes_by_calendar.csv`, and `gold_crimes_by_electoral_period.csv`. Default export location is `data/gold` for local behavior.
- `src/violence_etl/pipeline.py` and `src/violence_etl/cli.py` orchestrate `download`, `ingest-bronze`, `build-gold --export-csv`, and `run-all --export-csv`.
- The silver layer has no CSV artifact exports today, but the silver container secret must still be retrieved and configured.
- Tests and notebooks rely on local filesystem paths under `data/` and temporary directories.

## Requirements and constraints

1. In `ENV=PROD`, `get_settings()` must eagerly fetch and validate blob storage configuration from Key Vault using `KeyVaultClient` and the same credential pattern already used for secret access (`DefaultAzureCredential` by default, lazy Azure imports), so missing or invalid configuration fails fast at startup.
2. Read the following Key Vault secrets in `PROD`: `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, `GOLDCONTAINER`. All four are required and must be non-empty.
3. Keep `KeyVaultClient` generic. Do not add blob-specific secret names, container logic, or Azure Storage SDK usage to it.
4. Place blob-specific secret retrieval and configuration assembly in `src/violence_etl/config/settings.py` or a settings-level helper/module used by settings. Follow the existing pattern of keeping provider-specific secret names outside the generic client (similar to `postgres_url_from_key_vault`).
5. In `ENV=DEV` and `ENV=TEST`, do not require Azure Blob Storage configuration, do not require Azure Storage packages at runtime, and keep local `data/` behavior unchanged.
6. Introduce an artifact storage abstraction so bronze and gold persistence logic selects a backend by environment/config:
   - Local filesystem backend for `DEV`/`TEST`.
   - Azure Blob Storage backend for `PROD`.
7. Bronze landing/raw CSV artifacts must be stored in and read from the bronze container in `PROD`. When export is requested in `PROD`, the four gold export CSV artifacts must always be written to the configured gold container root. CLI flags remain unchanged, and `export_dir` applies only to `DEV`/`TEST` and local behavior.
8. Blob paths/naming must correspond to the current local layout (see design).
9. Bronze ingestion must be able to read the landing CSV from blob storage in `PROD`.
10. The `csv_path` argument to bronze ingestion remains a local filesystem override/input path. When provided in `PROD`, its bytes are read locally and resulting bronze artifacts are written to blob storage.
11. `download` command behavior remains logically the same: fetch source bytes, persist landing artifact, and report location, sha256, and whether it was newly written. In `PROD`, the reported location is the blob name within the bronze container (for example `landing/<sha256>.csv`).
12. Retrieve and store the silver container configuration in `PROD` even though no silver CSV artifacts are produced today.
13. Add `azure-storage-blob` as a runtime dependency for production blob access. Azure SDK imports must be lazy so `DEV`/`TEST` and unit tests without Azure packages installed can still run local flows.
14. Authentication to Azure Blob Storage uses `DefaultAzureCredential` (same credential pattern). No connection strings or storage account keys in code or environment-based secret plumbing beyond Key Vault.
15. Tests must cover the new behavior with mocks/fakes and no network calls.
16. No source code is modified by this specification task; this document defines implementation work to follow.

## Assumptions

- `ETL_BRONZE_DIR` remains meaningful for local `DEV`/`TEST` artifact storage and default local behavior. In `PROD`, blob containers define artifact locations; local bronze directory is not used for persisted bronze/gold CSV artifacts.
- In `PROD`, artifact identifiers stored or reported for bronze artifacts (`source_file`, landing location) are blob names within the container (for example `landing/<sha256>.csv`, `raw/yi5j-5fe9_<utcstamp>.csv`), with the container implied by the artifact/layer.
- Existing database schema and medallion table semantics do not change as part of this feature.
- `SILVCONTAINER` is reserved for future silver CSV/intermediate artifact exports; no new silver file outputs are introduced now.

## Proposed design/approach

### Configuration model

Blob storage configuration is defined in settings:
- `BlobStorageConfig` (frozen dataclass): `storage_account_name`, `bronze_container`, `silver_container`, `gold_container`.
- `Settings` includes `blob_storage: Optional[BlobStorageConfig] = None`.

Resolution rules:
- `DEV`/`TEST`: `blob_storage` is `None`; `bronze_dir` continues to drive local artifact paths.
- `PROD`: `AZURE_KEYVAULT_URL` remains required. `get_settings()` eagerly fetches and validates blob storage config from Key Vault by reading `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER`. Missing or invalid values cause startup/configuration failure.
- Secret retrieval is implemented by the settings-level helper `blob_storage_config_from_key_vault(vault_url, credential=None, client=None)`, which:
  - Uses an injected secret client when provided, otherwise instantiates generic `KeyVaultClient(vault_url, credential=credential)`.
  - Reads all four secrets and validates they are non-empty via `KeyVaultClient.get_secret`.
  - Returns `BlobStorageConfig`.
- `get_settings()` assembles settings in one place and, in `PROD`, resolves blob storage config eagerly so missing or misconfigured storage secrets fail fast with clear errors.
- Database credential resolution remains separate (`postgres_url_from_key_vault` / `database_url_object()`).

### Storage and client components

Artifact persistence is split between a low-level object storage client and artifact-level storage services.

- `src/violence_etl/clients/object_storage.py`: `ObjectStorageClient` is a provider-neutral low-level object/container client.
  - Accepts `storage_account_name`, optional `credential`, and optional injected `service_client`.
  - When no `service_client` is supplied, lazily imports Azure SDK dependencies, defaults credential to `DefaultAzureCredential` when needed, builds the account URL `https://<storage_account_name>.blob.core.windows.net`, and creates the backing service client.
  - Exposes `exists(container_name, blob_name)`, `upload(container_name, blob_name, data, overwrite=False)`, and `download(container_name, blob_name)`.
  - Supports injected `service_client` for tests without importing or installing Azure SDK packages. No cloud provider name appears in the module name.
- `src/violence_etl/storage/__init__.py`: minimal package marker with no factory or business logic.
- `src/violence_etl/storage/factory.py`: creational selection logic.
  - `ArtifactStorageFactory.create(settings, ...)` returns `LocalArtifactStorage(settings.bronze_dir)` for SQLite environments and `BlobArtifactStorage(settings.blob_storage, ...)` for `PROD`.
  - Raises a clear error if `ENV=PROD` but blob storage configuration is missing.
  - `get_artifact_storage(...)` is a convenience wrapper around the factory.
  - Factory methods accept injection hooks for testing (including service/storage client and credential pass-through) without changing runtime behavior.
- `src/violence_etl/storage/local_storage.py`: `LocalArtifactStorage` artifact service for local filesystem persistence.
  - Stores landing/raw artifacts under `bronze_dir` using existing local naming.
  - Implements `landing_location(sha)`, `write_landing(data)`, `write_run_raw_copy(data)`, `read_landing_csv(sha)`, and `export_gold_csvs(export_dir, ...)`.
  - Exports gold CSV files to the provided local `export_dir`.
- `src/violence_etl/storage/blob_storage.py`: `BlobArtifactStorage` artifact service for container-backed persistence in `PROD`.
  - Holds `BlobStorageConfig` and composes `ObjectStorageClient` (or accepts an injected storage/service client).
  - Implements artifact-level behavior: landing/raw blob naming, bronze landing existence/write/read operations, and gold export uploads.
  - Implements `landing_location(sha)`, `write_landing(data)`, `write_run_raw_copy(data)`, `read_landing_csv(sha)`, and `export_gold_csvs(export_dir, ...)`.
  - Writes all gold CSV exports to the configured gold container root regardless of `export_dir`, preserving the `export_dir` parameter for interface consistency with local behavior.

No `storage/azure_blob.py`, `storage/local.py`, `AzureBlobArtifactStorage`, or factory logic in `storage/__init__.py` exists in the implemented layout.

### Backend selection and integration

- `transformations.bronze.ingest_bronze`, `transformations.gold.build_gold`, and CLI `download` obtain the active artifact storage service via `get_artifact_storage(settings)` from `storage.factory`.
- Bronze artifact operations use storage service methods for run raw copy writes, landing writes, landing location identifiers, and landing CSV reads.
- Gold export uses `storage.export_gold_csvs(...)`; `DEV`/`TEST` write to a local export directory while `PROD` writes to the gold container root.
- `utils.io` continues to provide source download, hashing, timestamp, and local filesystem helpers used by local storage and other local-path flows. `download_source()` remains HTTP-only and returns bytes.
- CLI `download` stores the persisted landing identifier returned by `storage.write_landing(data)` in a `path` variable and reports it as the landing location.

### Blob paths and naming conventions

`PROD` blob naming mirrors the current local relative layout. These blob names are the artifact identifiers stored or reported for the corresponding artifacts in `PROD`, with the container implied by the artifact/layer:

Bronze container (`BRZECONTAINER`):
- Landing artifact: `landing/<sha256>.csv`
- Run raw copy: `raw/yi5j-5fe9_<utcstamp>.csv` (same `SOURCE_STEM` and UTC stamp format)

Gold container (`GOLDCONTAINER`):
- `gold_top5_departments.csv`
- `gold_crimes_by_department.csv`
- `gold_crimes_by_calendar.csv`
- `gold_crimes_by_electoral_period.csv`
- Files are written at the container root with the same filenames currently produced in `data/gold`.

Silver container (`SILVCONTAINER`):
- No CSV artifacts written by current pipeline stages.
- Container name must be retrieved/configured now as a reserved extension point for future silver exports or intermediate artifact persistence (for example future `silver/*.csv` or rejected-row exports) without changing secret/config contracts.

### Bronze ingestion, read behavior, and local overrides

- `download_source()` remains an HTTP download that returns bytes; only artifact persistence moves to blob in `PROD`.
- When `csv_path` is `None` (normal flow):
  - Download bytes.
  - Persist a run-stamped raw copy through the active storage service.
  - Persist landing content through the active storage service. If the landing artifact already exists, landing bytes are not rewritten (preserving current dedupe semantics) while a run-stamped raw copy is still created.
  - Read landing CSV content from the active storage service for ingestion.
- When `csv_path` is provided (local override):
  - Read bytes from the local filesystem path (works in `DEV`/`TEST`/`PROD`).
  - Write run raw copy and landing artifacts to the active backend (blob in `PROD`, local in `DEV`/`TEST`).
  - Read landing from the active backend for schema validation/ingestion.
- Landing CSV read behavior:
  - `LocalArtifactStorage.read_landing_csv` reads from the local landing path with identical pandas options.
  - `BlobArtifactStorage.read_landing_csv` downloads blob bytes and parses with `pandas.read_csv` using the same options (`dtype=str`, `keep_default_na=False`, `quoting=csv.QUOTE_ALL`).
- Hashing:
  - Bronze ingestion continues using in-memory sha256 for downloaded/read bytes.
  - `sha256_file`/`file_sha_or_none` remain local-path helpers in `utils.io`; artifact identifiers in `PROD` are blob names and storage-aware flows do not depend on treating them as filesystem paths.
- `landing_location(sha)` provides the backend-neutral landing artifact identifier (local path in `DEV`/`TEST`, blob name within the container in `PROD`) used for persistence, reads, and reporting.

### Gold export behavior

- `build_gold(..., export_csv=True, export_dir="data/gold")` remains the logical API.
- `DEV`/`TEST`: `LocalArtifactStorage.export_gold_csvs` writes the four CSV files to the local `export_dir` with current filenames and logging behavior.
- `PROD`: when `export_csv` is true, `BlobArtifactStorage.export_gold_csvs` always uploads the same four CSV files to the configured gold container root. CLI flags remain unchanged, and `export_dir` is treated as `DEV`/`TEST` and local behavior only.
- CSV content/column order remains identical to current exports.

### Download command behavior

- `download` continues to fetch source bytes, persist the landing artifact via storage, and print size, sha256, landing location, and whether newly written.
- `DEV`/`TEST`: landing location is the local landing path.
- `PROD`: landing location is the blob name within the bronze container (for example `landing/<sha256>.csv`), with the container implied by the landing artifact/layer.
- `cli.py` stores the returned landing identifier in a `path` variable when reporting command output.

### Authentication and lazy imports

- Blob access uses `DefaultAzureCredential` by default.
- `ObjectStorageClient` lazily imports `azure.identity` and `azure.storage.blob` only when creating a real service client (not when a `service_client` is injected).
- Importing local-only modules/paths in `DEV`/`TEST` must not require `azure-storage-blob`.
- `KeyVaultClient` remains the only generic secret client and must not import or depend on storage SDK classes.

### Data flow summary

1. `get_settings()` builds environment settings. In `PROD`, `AZURE_KEYVAULT_URL` is required and `get_settings()` eagerly fetches and validates blob storage config from Key Vault at startup; DB and blob secret names remain settings concerns.
2. CLI/pipeline stages request artifact storage through `storage.factory.get_artifact_storage(settings)`.
3. `DEV`/`TEST`: `LocalArtifactStorage` reads/writes under `data/` paths.
4. `PROD`: `BlobArtifactStorage` uses `ObjectStorageClient` to access `BRZECONTAINER` and `GOLDCONTAINER` on `https://<STORAGEACCOUNT>.blob.core.windows.net` with `DefaultAzureCredential` (`SILVCONTAINER` configured for future use).
5. Bronze writes landing/raw artifacts and reads landing CSV from the active backend for ingestion into the warehouse.
6. Gold builds tables in the warehouse and, if requested, exports gold CSV artifacts through the active backend.

## Implementation tasks/steps

1. Update settings/config:
   - Add `BlobStorageConfig` and extend `Settings` with `blob_storage`.
   - Add `blob_storage_config_from_key_vault` to read `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, and `GOLDCONTAINER` from Key Vault via generic `KeyVaultClient`.
   - Wire `get_settings()` to eagerly fetch and validate blob storage config in `PROD` while preserving `DEV`/`TEST` defaults.
2. Add low-level object storage client:
   - Create `clients/object_storage.py` with provider-neutral `ObjectStorageClient`.
   - Implement lazy Azure SDK imports, credential/account URL construction, and `exists/upload/download` operations.
   - Support injected `service_client` for tests.
3. Add artifact storage services and factory:
   - Keep `storage/__init__.py` minimal with no factory/business logic.
   - Implement `LocalArtifactStorage` in `storage/local_storage.py`.
   - Implement `BlobArtifactStorage` in `storage/blob_storage.py` using `ObjectStorageClient` for artifact-level bronze/gold operations.
   - Implement `ArtifactStorageFactory` and `get_artifact_storage` in `storage/factory.py`.
4. Integrate storage into ETL flows:
   - Use storage services in `transformations/bronze.py`, `transformations/gold.py`, and `cli.py` for landing/raw persistence, landing reads, download reporting, and gold exports.
   - Keep `csv_path` as a local override input; in `PROD` persist resulting artifacts to blob.
   - Preserve `utils.io` download/hash/local helpers and current local semantics.
5. Dependencies and packaging:
   - Add `azure-storage-blob` to runtime dependencies (with version pin/marker consistent with project policy).
   - Confirm lazy imports avoid breaking local/test environments without Azure extras.
6. Tests:
   - Add/update unit tests for blob config resolution, factory selection, `ObjectStorageClient`, and blob/local artifact operations using fakes/mocks.
   - Update existing tests only as needed for storage/config seams; keep local filesystem behavior unchanged in `DEV`/`TEST`.
7. Documentation:
   - Update README, `.env.example` notes if applicable, and PLAN/docs to describe blob storage configuration and `PROD` artifact locations.
8. Validation:
   - Run lint and full test suite (offline) and verify no regressions in `DEV`/`TEST`.

## Testing and validation plan

Automated tests (no network, no real Azure calls):
- Settings/config:
  - `PROD` resolves all four blob secrets from a fake/injected Key Vault client and populates `BlobStorageConfig`.
  - Missing/empty `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, or `GOLDCONTAINER` raises clear validation errors.
  - `DEV`/`TEST` do not require blob secrets or blob config and keep existing defaults (`bronze_dir` etc.).
  - In `PROD`, `get_settings()` fails fast at startup/config load on missing or invalid blob secrets.
- Object storage client and backends:
  - Factory selection returns local storage for `DEV`/`TEST` and blob storage for `PROD`.
  - `ObjectStorageClient` constructs/uses the service client lazily, supports injected `service_client`, and performs `exists/upload/download` operations without network calls in tests.
  - Local backend preserves current landing/raw/gold file paths and contents.
  - Blob backend composes `ObjectStorageClient` (or injected storage client) and asserts container selection, blob names (`landing/...`, `raw/...`, gold filenames), upload/download calls, and existence checks.
  - Landing dedupe semantics preserved: existing landing artifact not overwritten unnecessarily.
  - CSV read from blob uses correct pandas parsing options and yields expected DataFrame content.
- Bronze/gold flows:
  - `ingest_bronze` in blob mode writes raw and landing artifacts, reads landing from blob, and records expected `source_file`/`source_sha256` behavior.
  - `ingest_bronze` with `csv_path` reads local input but writes artifacts to the active backend (blob in `PROD` case, via fakes).
  - `build_gold(export_csv=True)` writes/exports all four gold CSV artifacts to the correct backend target with expected filenames and content. In `PROD`, exports go to the configured gold container root regardless of `export_dir`.
  - `download` command path stores landing in the active backend and reports correct landing identifier (`path`), sha256, and new flag. In `PROD`, the reported location is the landing blob name within the bronze container.
- Compatibility and isolation:
  - `DEV`/`TEST` flows run without `azure-storage-blob` installed (simulate missing import where feasible).
  - Injected/fake clients prevent any network access.

Validation commands (implementation phase):
- `make lint`
- `python -m pytest tests -q`
- Optional targeted tests for new storage/settings/client modules during development.

## Documentation updates needed

- `README.md`: document `PROD` blob artifact storage, required Key Vault secrets (`STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, `GOLDCONTAINER`), that `SILVCONTAINER` is reserved/configured for future silver artifacts, and clarify that local `data/` paths apply to `DEV`/`TEST`.
- `.env.example`: add comments for new Key Vault secret names expected in `PROD` (no local secret values). Clarify `ETL_BRONZE_DIR` scope if needed.
- `docs/PLAN.md`: update architecture/design notes to include artifact storage abstraction, object storage client, and blob layout for bronze/gold.
- `specs/INDEX.md`: keep feature `0002` entry accurate (included in this specification task).

## Risks, edge cases, and rollout notes

Risks and edge cases:
- Artifact identifiers in `PROD` are blob names within the container (not fully qualified URLs), with the container implied by the artifact/layer. Operators and downstream consumers must interpret them in that context.
- Partial writes or transient storage errors in `PROD` can leave raw and landing artifacts out of sync; implementation should preserve current write order/intent and surface errors clearly.
- Large CSV reads from blob: reading into memory is acceptable at current dataset scale but should be implemented efficiently (streaming where practical).
- `DefaultAzureCredential` behavior differs across environments (managed identity, CLI, workload identity); missing permissions or misconfigured identity will fail at runtime in `PROD`.
- Container existence/permissions: secrets may be valid but containers may not exist or may deny access; errors must be explicit.
- Pandas CSV parsing from bytes/streams must preserve exact options to avoid subtle data changes.

Rollout notes:
- No database migration required unless unrelated; storage changes affect file artifacts only.
- Deploy with `azure-storage-blob` available in `PROD` runtime image/environment.
- Ensure Key Vault contains `STORAGEACCOUNT`, `BRZECONTAINER`, `SILVCONTAINER`, `GOLDCONTAINER` and that the runtime identity can read secrets and access blob containers before enabling `PROD` runs.
- Validate in a non-production `PROD`-like environment first (`download`, `ingest-bronze`, `build-gold --export-csv`, `run-all`) and confirm artifact locations and idempotency.
- `DEV`/`TEST` users should see no behavior change.
