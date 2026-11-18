"""Azure Key Vault client for PostgreSQL warehouse credentials."""
from __future__ import annotations

from sqlalchemy.engine import URL

SECRET_HOST = "PGHOST"
SECRET_PORT = "PGPORT"
SECRET_USER = "PGUSER"
SECRET_PASSWORD = "PGPASSWORD"
SECRET_DATABASE = "PGDATABASE"


def postgres_url_from_key_vault(vault_url: str) -> URL:
    """Fetch PostgreSQL credentials from Azure Key Vault and return a SQLAlchemy URL.

    Credentials are read from separate secrets (PGHOST, PGPORT, PGUSER,
    PGPASSWORD, PGDATABASE) using DefaultAzureCredential. The returned URL
    targets Azure PostgreSQL with sslmode=require.
    """
    if not vault_url:
        raise ValueError("AZURE_KEYVAULT_URL is required when ENV=PROD")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise ImportError(
            "Azure Key Vault support requires 'azure-identity' and "
            "'azure-keyvault-secrets' to be installed"
        ) from exc

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)

    host = _require_secret(client, SECRET_HOST)
    port_raw = _require_secret(client, SECRET_PORT)
    user = _require_secret(client, SECRET_USER)
    password = _require_secret(client, SECRET_PASSWORD)
    database = _require_secret(client, SECRET_DATABASE)

    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Key Vault secret PGPORT must be an integer") from exc

    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"sslmode": "require"},
    )


def _require_secret(client, name: str) -> str:
    value = client.get_secret(name).value
    if value is None or value == "":
        raise ValueError("Key Vault secret '{0}' is empty or missing".format(name))
    return value
