"""Batched metric reads (PERFORMANCE.md) equal the per-experiment, full-model reads.

* every field of a light result view equals the same field of the fully validated output;
* ``get_metrics_many`` equals ``get_metrics`` (and its ``ExperimentMetrics`` keeps the
  flag order of ``latest_results``);
* ``latest_result_refs_many`` / ``latest_result_ids_many`` / ``get_result_heads`` equal the
  corresponding parts of ``latest_results`` / ``get_result``;
* Records reads a constant number of queries, not one batch per experiment.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.analysis import records, service
from app.analysis.metrics_view import OUTPUT_VIEW
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, ExperimentCreate


def _subset(view: Any, full: Any, path: str = "output") -> None:
    """Every key of ``view`` (recursively) has the same value in ``full``."""
    if isinstance(view, dict):
        assert isinstance(full, dict), path
        for k, v in view.items():
            assert k in full, f"{path}.{k}"
            _subset(v, full[k], f"{path}.{k}")
    elif isinstance(view, list):
        assert isinstance(full, list) and len(view) == len(full), path
        for i, (v, f) in enumerate(zip(view, full, strict=True)):
            _subset(v, f, f"{path}[{i}]")
    else:
        assert view == full and type(view) is type(full), (path, view, full)


def test_result_views_are_subsets_of_full_outputs(session: Session, seeded: dict[str, int]) -> None:
    results = service.list_results(session)
    assert {r.kind for r in results} >= {"calibration", "recovery", "is_response", "limits"}
    for res in results:
        stored = res.output.model_dump_json()
        view = OUTPUT_VIEW.validate_json(stored)
        _subset(view.model_dump(), res.output.model_dump())


def test_metrics_many_equals_single(session: Session, seeded: dict[str, int]) -> None:
    ids = [e.id for e in eln.list_experiments(session, seeded["project"])]
    many = service.get_metrics_many(session, ids)
    assert list(many) == ids
    analyzed = 0
    for i in ids:
        single = service.get_metrics(session, i)
        assert many[i] == single
        latest = service.latest_results(session, i)
        assert single.flags == [f for r in latest.values() for f in r.flags]  # order kept
        analyzed += single.analyzed
    assert analyzed >= 5


def test_result_heads_and_latest_refs(session: Session, seeded: dict[str, int]) -> None:
    ids = [e.id for e in eln.list_experiments(session, seeded["project"])]
    refs = service.latest_result_refs_many(session, [*ids, 99_999])
    result_ids = service.latest_result_ids_many(session, ids)
    assert refs[99_999] == {}
    for i in ids:
        latest = service.latest_results(session, i)
        assert list(refs[i]) == list(latest) == list(result_ids[i])
        for kind, res in latest.items():
            head = refs[i][kind]
            assert (head.id, head.experiment_id, head.kind) == (res.id, i, kind)
            assert (head.method_version, head.flags) == (res.method_version, res.flags)
            assert result_ids[i][kind] == res.id
    all_ids = [r.id for r in service.list_results(session)]
    heads = service.get_result_heads(session, [*all_ids, 99_999])
    assert sorted(heads) == sorted(all_ids)
    for rid, head in heads.items():
        full = service.get_result(session, rid)
        assert head.model_dump() == full.model_dump(
            include={"id", "experiment_id", "kind", "method_version", "flags"}
        )


def _statements(session: Session) -> int:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        records.by_period(session)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(statements)


def test_records_query_count_does_not_grow_per_experiment(
    session: Session, seeded: dict[str, int]
) -> None:
    before = _statements(session)
    for i in range(5):
        eln.create_experiment(
            session,
            seeded["project"],
            ExperimentCreate(
                code=f"#R{i}",
                title="r",
                performed_on=date(2026, 3, 1),
                raw_note="n",
                condition_block=ConditionBlock(ph=5.0),
            ),
        )
    assert _statements(session) == before  # was ≥ 4 more queries per experiment
