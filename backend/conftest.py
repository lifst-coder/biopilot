"""Shared pytest fixtures for every module's tests (rootdir conftest)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import AIMode, Settings
from app.core.db import Database
from app.main import create_app
from app.seed.loader import seed

T = TypeVar("T", bound=BaseModel)


@pytest.fixture
def db() -> Database:
    database = Database("sqlite://")
    database.create_all()
    return database


@pytest.fixture
def session(db: Database) -> Iterator[Session]:
    with db.session() as s:
        yield s


@pytest.fixture
def seeded(session: Session) -> dict[str, int]:
    """Seed the reference project; returns ``{"project": id, "#018": id, ...}``."""
    from app.eln import service as eln

    project_id = seed(session)
    session.commit()
    ids = {"project": project_id}
    for exp in eln.list_experiments(session, project_id):
        ids[exp.code] = exp.id
    return ids


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(auto_seed=True, anthropic_api_key=None), Database("sqlite://"))
    with TestClient(app) as c:
        yield c


class FakeGateway:
    """Test double for :class:`app.core.llm.LLMGateway`.

    ``responder`` receives ``(schema, prompt)`` and returns an instance or ``None``.
    """

    def __init__(
        self,
        responder: Callable[[type[BaseModel], str], BaseModel | None],
        mode: AIMode = "claude",
    ) -> None:
        self._responder = responder
        self._mode = mode
        self.calls: list[dict[str, Any]] = []

    @property
    def mode(self) -> AIMode:
        return self._mode

    @property
    def model_name(self) -> str | None:
        return "fake-claude" if self._mode == "claude" else None

    def generate(self, *, system: str, prompt: str, schema: type[T]) -> T | None:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        result = self._responder(schema, prompt)
        return result if isinstance(result, schema) else None


@pytest.fixture
def fake_gateway_factory() -> type[FakeGateway]:
    return FakeGateway
