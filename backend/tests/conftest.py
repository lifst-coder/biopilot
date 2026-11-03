"""Fixtures for the ``lab`` seed profile (two projects, 42 experiments).

Seeding the lab takes about a second, so it is done once per test session into a
shared in-memory database. ``lab_session`` hands each test its own session and rolls
back whatever the test wrote, so tests stay independent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.db import Database
from app.seed.loader import SeedResult, seed_profile
from app.seed.spec import SeedSpec, load_seed_spec


@pytest.fixture(scope="session")
def lab_db() -> tuple[Database, SeedResult]:
    database = Database("sqlite://")
    database.create_all()
    with database.session() as s:
        result = seed_profile(s, "lab")
        s.commit()
    return database, result


@pytest.fixture
def lab(lab_db: tuple[Database, SeedResult]) -> SeedResult:
    """Ids created by the lab profile (``experiment_ids[("residue", "#024")]`` …)."""
    return lab_db[1]


@pytest.fixture
def lab_session(lab_db: tuple[Database, SeedResult]) -> Iterator[Session]:
    with lab_db[0].session() as s:
        yield s
        s.rollback()


@pytest.fixture(scope="session")
def lab_spec() -> SeedSpec:
    return load_seed_spec("lab")
