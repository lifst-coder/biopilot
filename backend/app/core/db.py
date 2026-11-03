"""SQLAlchemy engine, declarative base and session dependency.

Table naming convention: ``<module>_<entity>`` (e.g. ``eln_experiments``) so that
parallel work on different modules never collides on table names.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base shared by every module's ORM models."""


def utcnow() -> datetime:
    """Timezone-aware UTC now (single source for timestamps)."""
    return datetime.now(UTC)


def make_engine(url: str) -> Engine:
    """Create an engine; in-memory SQLite uses a StaticPool so all sessions share it."""
    kwargs: dict[str, object] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]  # noqa: ANN001, ANN202
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


class Database:
    """Holds an engine + session factory. One instance per app (tests make their own)."""

    def __init__(self, url: str) -> None:
        self.engine = make_engine(url)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        """Create all tables registered on :data:`Base.metadata`."""
        import app.models_registry  # noqa: F401  (registers every module's models)

        Base.metadata.create_all(self.engine)

    def prepare_schema(self) -> None:
        """Migrate to the current schema with Alembic (see :mod:`app.core.migrate`)."""
        from app.core.migrate import prepare_schema

        prepare_schema(self.engine)

    def session(self) -> Session:
        """Open a new session."""
        return self.session_factory()

    def session_dependency(self) -> Iterator[Session]:
        """FastAPI dependency body: one session per request, committed on success."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
