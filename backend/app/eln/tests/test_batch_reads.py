"""Batched reads (PERFORMANCE.md) return exactly what the per-item reads return.

``list_experiments_full`` / ``get_experiments`` read revisions, addenda, files and
dataset kinds with one query each for all experiments; ``list_project_datasets`` /
``get_datasets`` read successors for all datasets at once; dataset successors are found
through ``ix_eln_datasets_supersedes_dataset_id``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.eln import service
from app.eln.schemas import (
    ConditionBlock,
    DatasetCreate,
    ExperimentAddendumCreate,
    ExperimentCreate,
    ExperimentMetadataUpdate,
    ProjectCreate,
)

CAL = "injection_id,level_ng_ml,analyte,analyte_area,is_area\nCAL-01,5,x,100,1000\n"


@pytest.fixture
def project(session: Session) -> int:
    """Experiments with revisions, addenda and datasets, one superseded twice."""
    pid = service.create_project(session, ProjectCreate(name="P")).id
    parent: int | None = None
    for i in range(6):
        exp = service.create_experiment(
            session,
            pid,
            ExperimentCreate(
                code=f"#{i:03d}",
                title=f"t{i}",
                performed_on=date(2026, 1, 1 + i % 3),
                parent_experiment_id=parent,
                raw_note="n",
                condition_block=ConditionBlock(ph=5.0 + i / 10),
            ),
        )
        parent = exp.id
        if i % 2:
            service.update_metadata(session, exp.id, ExperimentMetadataUpdate(title=f"t{i}b"))
            service.add_addendum(session, exp.id, ExperimentAddendumCreate(note=f"a{i}"))
        if i % 3 == 0:
            first = service.create_dataset(
                session, exp.id, DatasetCreate(kind="calibration", filename="c.csv", content=CAL)
            )
            for _ in range(2):  # superseded twice: the successor is the earliest re-upload
                service.create_dataset(
                    session,
                    exp.id,
                    DatasetCreate(
                        kind="calibration",
                        filename="c2.csv",
                        content=CAL,
                        supersedes_dataset_id=first.id,
                    ),
                )
    session.commit()
    return pid


@contextmanager
def _count_queries(session: Session) -> Iterator[list[str]]:
    seen: list[str] = []

    def before(*args: Any) -> None:
        seen.append(args[2])

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


def test_experiment_batches_equal_single_reads(session: Session, project: int) -> None:
    full = service.list_experiments_full(session, project)
    singles = [service.get_experiment(session, e.id) for e in full]
    assert full == singles
    assert any(e.revision > 1 for e in full) and any(e.addenda for e in full)
    assert any(e.dataset_kinds for e in full)
    ids = [e.id for e in full]
    assert service.get_experiments(session, [*ids, 99_999]) == {e.id: e for e in singles}


def test_experiment_listing_query_count_is_constant(session: Session, project: int) -> None:
    with _count_queries(session) as small:
        service.list_experiments_full(session, project)
    for i in range(10):
        service.create_experiment(
            session,
            project,
            ExperimentCreate(
                code=f"#X{i}",
                title="x",
                performed_on=date(2026, 2, 1),
                raw_note="n",
                condition_block=ConditionBlock(ph=5.0),
            ),
        )
    with _count_queries(session) as large:
        service.list_experiments_full(session, project)
    assert len(large) == len(small) < 10  # a fixed set of queries, none per experiment


def test_dataset_batches_equal_single_reads(session: Session, project: int) -> None:
    by_exp = service.list_project_datasets(session, project)
    exps = service.list_experiments_full(session, project)
    for e in exps:
        assert by_exp.get(e.id, []) == service.list_datasets(session, e.id)
    ids = [d.id for ds in by_exp.values() for d in ds]
    metas = service.get_datasets(session, ids)
    assert metas == {i: service.get_dataset(session, i) for i in ids}
    superseded = [d for d in metas.values() if d.superseded_by_dataset_id is not None]
    assert len(superseded) == 2
    for d in superseded:  # the earliest re-upload is the successor
        successors = [x.id for x in metas.values() if x.supersedes_dataset_id == d.id]
        assert d.superseded_by_dataset_id == min(successors)
    assert service.get_dataset_contents(session, ids) == {
        i: service.get_dataset_content(session, i) for i in ids
    }


def test_successor_lookup_uses_the_index(session: Session, project: int) -> None:
    plan = session.execute(
        text("EXPLAIN QUERY PLAN SELECT id FROM eln_datasets WHERE supersedes_dataset_id = 1")
    ).all()
    assert any("ix_eln_datasets_supersedes_dataset_id" in str(row) for row in plan), plan
