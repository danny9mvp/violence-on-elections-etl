# 0001 KeyVaultIntegration

## Summary and goals

Split generic Azure Key Vault secret access from PostgreSQL-specific configuration. The new client can read any secret. The settings module owns PostgreSQL secret names, port parsing, and SQLAlchemy URL construction. Public runtime behavior stays the same for DEV, TEST, and PROD.

## Existing behavior

- `src/violence_etl/config/keyvault.py` defines `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`. It lazily imports `DefaultAzureCredential` and `SecretClient`, reads the five secrets, parses `PGPORT` with `int()`, and returns a `URL.create("postgresql+psycopg", ..., query={"sslmode": "require"})`. `_require_secret()` rejects empty or missing values.
- `src/violence_etl/config/settings.py` defines frozen `Settings`, `get_settings()`, `database_url_object()`, `database_url()` and masked `database_url_display()`. `get_settings()` requires `AZURE_KEYVAULT_URL` when `ENV=PROD`. `database_url_object()` returns a SQLite URL for `DEV`/`TEST` and calls the Key Vault helper for `PROD`.
- `src/violence_etl/db/connection.py` calls `database_url_object()` through `_database_url_object`, so it needs no behavior change.
- `tests/test_settings.py` monkeypatches `violence_etl.config.keyvault.postgres_url_from_key_vault` for the PROD case.

## Requirements and constraints

1. Add `src/violence_etl/clients/key_vault.py` with `KeyVaultClient(vault_url, credential=None, secret_client=None)` and `get_secret(name) -> str`.
2. The client must contain no SQLAlchemy, PostgreSQL, or PG names. It only handles vault access and non-empty string secrets.
3. Azure imports must stay lazy. When `secret_client` is injected, the constructor must not import `azure.identity` or `azure.keyvault.secrets`.
4. Move PostgreSQL secret names, port parsing, and URL building into a public module-level helper `postgres_url_from_key_vault(vault_url)` in `config/settings.py`. `database_url_object()` must call this helper.
5. Delete `src/violence_etl/config/keyvault.py` and remove all imports of it.
6. Update tests to patch the new helper and add fake-client tests that make no network calls.
7. Keep environment variables, secret names, URL dialect, `sslmode=require`, error behavior, and masking behavior unchanged.
8. Add no new mandatory dependency for `DEV`/`TEST`.

## Proposed design and data flow

### Components

- `src/violence_etl/clients/__init__.py`: empty package marker.
- `src/violence_etl/clients/key_vault.py`: `KeyVaultClient`. Constructor stores `vault_url`. If `credential` is `None`, lazily import `DefaultAzureCredential` and create it. If `secret_client` is `None`, lazily import `SecretClient` and create it with `vault_url` and `credential`. If either is supplied, use it as is. `get_secret(name)` calls `secret_client.get_secret(name).value`, rejects `None` or empty, and returns the value. Error messages are generic and use only the secret name.
- `src/violence_etl/config/settings.py`: keeps existing `URL` import. Adds private `PG_*` constants and public `postgres_url_from_key_vault(vault_url)`. The helper creates a `KeyVaultClient`, reads the five secrets, parses the port, and returns the same URL as today. It preserves the current missing-vault and invalid-port error messages.
- `src/violence_etl/db/connection.py`: no functional change. It continues to use `settings.database_url_object()`.

### Data flow

1. `make_engine()` calls `database_url_object()`.
2. For `DEV`/`TEST`, settings returns `sqlite:///...`.
3. For `PROD`, settings validates `key_vault_url` and calls its own `postgres_url_from_key_vault()`.
4. The helper builds `KeyVaultClient`, which reads secrets through the injected or lazily created Azure client.
5. The helper converts the secret values into a `postgresql+psycopg` URL with `sslmode=require`.
6. `database_url()` and `database_url_display()` render that URL with and without the password.

## Implementation tasks

1. Create `src/violence_etl/clients/__init__.py`.
2. Create `src/violence_etl/clients/key_vault.py` with `KeyVaultClient` as described.
3. Add `postgres_url_from_key_vault()` to `config/settings.py` and switch `database_url_object()` to call it directly.
4. Remove `src/violence_etl/config/keyvault.py`.
5. Update `tests/test_settings.py` to patch `violence_etl.config.settings.postgres_url_from_key_vault`.
6. Add `tests/test_key_vault_client.py` with fake credential and fake secret client coverage.
7. Update README, PLAN, and `.env.example` wording where the old module is named.
8. Run `make lint` and `python -m pytest tests -q`.

## Testing and validation

- Keep all existing settings tests, changing only the PROD monkeypatch target.
- Add a fake secret client exposing `get_secret(name)` that returns an object with a `value` attribute. Build the URL from it and assert dialect, host, port, user, database, password, and `sslmode`.
- Assert `get_secret()` raises `ValueError` for empty and missing values.
- Assert invalid `PGPORT` still raises `ValueError` with the existing message.
- Assert an injected `secret_client` works without Azure packages by blocking `azure.identity` and `azure.keyvault.secrets` imports in the test.
- Assert `DEV`/`TEST` URL building does not import the Key Vault client.
- Assert masked display still hides the password and unmasked display still includes it.
- Full suite must remain offline against SQLite. `make lint` must pass.

## Documentation updates needed

- `README.md`: mention `KeyVaultClient` as the generic secret reader and `settings.postgres_url_from_key_vault()` as the URL builder. Secret names and environment behavior stay the same.
- `docs/PLAN.md`: update the production design note with the new module locations.
- `.env.example`: no variable changes. Optionally clarify that secret retrieval is implemented by the generic client.

## Risks, edge cases, and rollout notes

- Empty secrets, missing secrets, invalid `PGPORT`, missing vault URL, Azure auth failure, and missing Azure packages must keep current failure behavior.
- Passwords containing URL-special characters remain safe because `URL.create()` handles escaping.
- The old monkeypatch path is a test detail, not a published API. External callers that imported `violence_etl.config.keyvault` would break, so verify with a repository-wide grep before deletion.
- Rollout is a single code change with no migration, no environment variable change, and no secret rotation. Deploy PROD after the test suite passes.

## Assumptions and open questions

- No application code outside tests imports `violence_etl.config.keyvault`.
- `KeyVaultClient` may later serve non-PostgreSQL secrets, so it must stay free of database names.
- Azure packages remain in runtime requirements as today. This change does not add them to `DEV`/`TEST`.
- Decisions on class name, helper location, and spec path were already made. No further clarification is needed.
