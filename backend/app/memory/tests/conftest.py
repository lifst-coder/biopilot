"""Memory test helpers: make sure higher-layer fact providers are registered."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.eln import service as eln
from app.eln.schemas import ConditionBlock, ExperimentCreate, ExperimentOut
from app.memory import ports
from app.wiring import install


@pytest.fixture(autouse=True)
def _providers() -> Iterator[None]:
    install()
    yield
    install()


@pytest.fixture
def no_providers() -> Iterator[None]:
    """Run a test with Memory standalone (no Analysis/Partner providers)."""
    saved = dict(ports._providers)
    ports._providers.clear()
    yield
    ports._providers.update(saved)


def make_child(
    session: Session, parent_id: int, code: str, note: str = "후속 실험", **overrides: object
) -> ExperimentOut:
    """Create a child experiment copying the parent's conditions with overrides."""
    parent = eln.get_experiment(session, parent_id)
    cond = parent.condition_block.model_dump(exclude_none=True) | overrides
    return eln.create_experiment(
        session,
        parent.project_id,
        ExperimentCreate(
            code=code,
            title=f"{code} 후속",
            author="테스트",
            performed_on=date(2026, 11, 1),
            parent_experiment_id=parent_id,
            raw_note=note,
            condition_block=ConditionBlock.model_validate(cond),
        ),
    )
