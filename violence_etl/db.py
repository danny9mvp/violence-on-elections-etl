"""Engine and session factory.

The engine is built from the settings module so the whole pipeline can target
either PostgreSQL or SQLite without any code change.
"""
from __future__ import annotations

import os
from typing import Optional, Union

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from violence_etl.settings import Settings, get_settings
from violence_etl.settings import database_url_object as _database_url_object


def make_engine(
    url: Optional[Union[str, URL]] = None,
    settings: Optional[Settings] = None,
) -> Engine:
    """Create an Engine for ``url``, or from settings when ``url`` is None.

    ``url`` may be a string or a :class:`sqlalchemy.engine.URL`.
    """
    if url is None:
        url = _database_url_object(settings or get_settings())

    # make_url accepts either a string or a URL and gives us the backend name.
    parsed = make_url(url)

    connect_args = {}
    if parsed.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        # Ensure the parent directory of the sqlite file exists.
        path = parsed.database
        if path and path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)

    return create_engine(url, future=True, connect_args=connect_args)


def make_session_factory(engine: Engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def make_session(engine: Optional[Engine] = None) -> Session:
    return make_session_factory(engine or make_engine())()


def ping(engine: Engine) -> bool:
    """Return True when a trivial query succeeds (used by validate/CLI)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
