"""Schema migrations (Alembic) for the app database.

Revisions live in ``app/core/migrations/versions``. :func:`prepare_schema` is what the app
runs at start-up:

* empty database → ``create_all`` + ``stamp head`` (fast path; ``tests/test_migrations.py``
  proves ``upgrade head`` builds the identical schema);
* database managed by Alembic → ``upgrade head``;
* tables but no ``alembic_version`` → a pre-Alembic database (created by ``create_all``
  before the merge). Its schema is unknown, so :class:`LegacyDatabaseError` is raised with
  the reset procedure from README ("기존 DB 재생성").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
#: Tables Alembic must never create/drop: the FTS5 index (+ shadow tables) of Memory.
EXCLUDED_TABLE_PREFIXES: tuple[str, ...] = ("memory_search_fts",)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Autogenerate filter: skip objects outside the declarative metadata (FTS5 tables)."""
    return not (type_ == "table" and name is not None and name.startswith(EXCLUDED_TABLE_PREFIXES))


class LegacyDatabaseError(RuntimeError):
    """The database has tables but was never stamped by Alembic."""


def alembic_config(engine: Engine | None = None) -> Config:
    """Alembic ``Config`` pointing at the core migrations (URL from ``engine`` if given)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if engine is not None:
        cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    return cfg


def head_revision() -> str:
    """The newest revision id."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None, "no Alembic revisions found"
    return head


def current_revision(engine: Engine) -> str | None:
    """Revision stamped in the database (``None`` if not managed by Alembic)."""
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Run ``alembic upgrade`` on ``engine`` (re-uses its connection; works in-memory)."""
    cfg = alembic_config(engine)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


def stamp(engine: Engine, revision: str = "head") -> None:
    """Record ``revision`` as current without running it."""
    cfg = alembic_config(engine)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.stamp(cfg, revision)


def prepare_schema(engine: Engine) -> None:
    """Bring the database to the current schema (see module docstring)."""
    import app.models_registry  # noqa: F401  (registers every module's models)
    from app.core.db import Base

    tables = set(inspect(engine).get_table_names())
    if "alembic_version" in tables:
        upgrade(engine)
        return
    if tables:
        raise LegacyDatabaseError(
            "This database predates Alembic (tables but no alembic_version). Its schema "
            "cannot be upgraded safely: delete the SQLite file and ./eln_storage, then restart "
            "to re-seed (README → '기존 DB 재생성')."
        )
    Base.metadata.create_all(engine)
    stamp(engine)
