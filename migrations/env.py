from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from violence_etl.models import Base
from violence_etl.settings import database_url_object, get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _configured_url():
    """Return the runtime URL.

    The CLI passes a :class:`sqlalchemy.engine.URL` through
    ``config.attributes`` so no value ever travels through ``ConfigParser``
    (which interpolates ``%`` and breaks on such passwords). When Alembic is
    driven directly, fall back to the environment-derived URL.
    """
    url = config.attributes.get("sqlalchemy.url")
    if url is None:
        url = database_url_object(get_settings())
    return url


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_configured_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_configured_url(), poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
