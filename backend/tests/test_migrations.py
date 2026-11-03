"""Alembic baseline (core): migrations build exactly the declarative schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import app.models_registry  # noqa: F401
from app.core import migrate
from app.core.db import Base, Database
from app.memory import service as memory
from app.seed.loader import seed


def _db(tmp_path: Path, name: str = "m.db") -> Database:
    return Database(f"sqlite:///{tmp_path / name}")


def _diff(db: Database) -> list[object]:
    with db.engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "include_object": migrate.include_object,
                "render_as_batch": True,
                "compare_type": True,
            },
        )
        return list(compare_metadata(ctx, Base.metadata))


def test_upgrade_head_matches_metadata(tmp_path: Path) -> None:
    db = _db(tmp_path)
    migrate.upgrade(db.engine)
    assert migrate.current_revision(db.engine) == migrate.head_revision()
    assert _diff(db) == []  # `alembic check` equivalent: no pending autogenerate ops
    tables = set(inspect(db.engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    cols = {c["name"]: c for c in inspect(db.engine).get_columns("partner_critiques")}
    assert cols["experiment_id"]["nullable"] is True  # NOT NULL → NULL in the merged schema


def test_fts_table_is_outside_migrations(tmp_path: Path) -> None:
    """Memory's lazily created FTS5 table must not show up as drift."""
    db = _db(tmp_path)
    db.prepare_schema()
    with Session(db.engine) as session:
        pid = seed(session)
        session.commit()
        memory.search(session, pid, "회수율")
        session.commit()
    assert any(t.startswith("memory_search_fts") for t in inspect(db.engine).get_table_names())
    assert _diff(db) == []


def test_prepare_schema_paths(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.prepare_schema()  # empty → create_all + stamp head
    assert migrate.current_revision(db.engine) == migrate.head_revision()
    db.prepare_schema()  # managed → upgrade head (no-op)
    assert migrate.current_revision(db.engine) == migrate.head_revision()

    legacy = _db(tmp_path, "legacy.db")
    legacy.create_all()  # pre-Alembic database: tables, no alembic_version
    with pytest.raises(migrate.LegacyDatabaseError, match="eln_storage"):
        legacy.prepare_schema()


def test_downgrade_base_drops_everything(tmp_path: Path) -> None:
    db = _db(tmp_path)
    migrate.upgrade(db.engine)
    cfg = migrate.alembic_config(db.engine)
    from alembic import command

    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    with db.engine.connect() as conn:
        left = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    assert {r[0] for r in left} <= {"alembic_version"}
