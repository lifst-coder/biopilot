"""Alembic environment: every module's tables on ``Base.metadata``, SQLite batch mode.

* ``render_as_batch=True`` — SQLite cannot ``ALTER COLUMN``; batch mode recreates the
  table (needed e.g. for ``partner_critiques.experiment_id`` NOT NULL → NULL).
* The FTS5 virtual table ``memory_search_fts`` and its shadow tables live outside the
  metadata (Memory creates them lazily on first search), so autogenerate ignores them.
* The connection comes from ``config.attributes["connection"]`` when the app runs the
  upgrade (:func:`app.core.migrate.upgrade`), otherwise from ``sqlalchemy.url`` /
  ``BIOPILOT_DATABASE_URL`` for the ``alembic`` CLI.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

import app.models_registry  # noqa: F401  (registers every module's models)
from app.core.config import Settings
from app.core.db import Base, make_engine
from app.core.migrate import include_object


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run() -> None:
    """Run migrations online (offline SQL generation is not supported)."""
    config = context.config
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    url = config.get_main_option("sqlalchemy.url") or Settings().database_url
    engine = make_engine(url)
    with engine.connect() as conn:
        _configure(conn)


run()
