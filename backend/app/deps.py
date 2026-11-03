"""FastAPI dependencies shared by all routers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.db import Database


def get_session(request: Request) -> Iterator[Session]:
    """Yield a request-scoped session bound to ``app.state.db``."""
    db: Database = request.app.state.db
    yield from db.session_dependency()
