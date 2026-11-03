"""Records across projects: grouping by condition value, author and month (stored values)."""

from __future__ import annotations

import statistics
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analysis import records, service
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, DatasetCreate, ExperimentCreate


def test_condition_groups_summarise_stored_recovery(
    session: Session, seeded: dict[str, int]
) -> None:
    out = records.by_condition(session, "cleanup_sorbent", contains="gcb")
    assert out.project_ids == [seeded["project"]]
    assert sum(g.experiment_count for g in out.groups) == 7
    assert out.groups[0].experiment_count >= out.groups[-1].experiment_count  # largest first
    gcb = next(g for g in out.groups if "GCB" in g.key)
    assert [e.code for e in gcb.experiments] == ["#024"]
    assert gcb.fail_count == 1 and gcb.fail_ratio == 1.0
    m = service.get_metrics(session, seeded["#024"])
    assert gcb.recovery_median_pct == m.recovery_mean_pct  # copied, not recomputed
    assert gcb.experiments[0].source_result_ids == m.source_result_ids
    c18 = next(g for g in out.groups if "C18" in g.key)
    values = [e.recovery_mean_pct for e in c18.experiments if e.recovery_mean_pct is not None]
    assert c18.recovery_n == len(values)
    assert c18.recovery_median_pct == statistics.median(values)
    assert c18.recovery_min_pct == min(values) and c18.recovery_max_pct == max(values)
    assert c18.fail_count == 0
    assert out.matched is not None and [e.code for e in out.matched.experiments] == ["#024"]


def test_missing_condition_key_is_its_own_group(session: Session, seeded: dict[str, int]) -> None:
    out = records.by_condition(session, "no_such_key")
    assert [g.key for g in out.groups] == [records.NO_VALUE]
    assert out.groups[0].experiment_count == 7
    assert out.matched is None


def test_months_and_gaps(session: Session, seeded: dict[str, int]) -> None:
    out = records.by_period(session)
    assert [g.key for g in out.months] == ["2026-09", "2026-10"]
    assert sum(g.experiment_count for g in out.months) == 7
    assert out.gaps == []  # weekly experiments: nothing ≥ 21 days
    weekly = records.by_period(session, gap_days=7)
    assert len(weekly.gaps) == 6 and all(g.days == 7 for g in weekly.gaps)
    first = weekly.gaps[0]
    assert first.start == date(2026, 9, 8) and [e.code for e in first.before] == ["#018"]


def test_operator_pairs_need_identical_conditions_and_different_authors(
    session: Session, seeded: dict[str, int]
) -> None:
    out = records.by_operator(session)
    assert {g.key for g in out.authors} == {"김연구", "이분석"}
    assert sum(g.experiment_count for g in out.authors) == 7
    # reference: #018 (김연구) vs #022 (김연구) share conditions but not people → no pair
    for pair in out.pairs:
        assert pair.experiment_a.author != pair.experiment_b.author
        assert pair.days_apart <= out.window_days
    # a same-protocol repeat by another person within the window becomes a pair (Welch)
    base = eln.get_experiment(session, seeded["#022"])
    rerun = eln.create_experiment(
        session,
        base.project_id,
        ExperimentCreate(
            code="#022b",
            title="반복 (다른 작업자)",
            author="이분석",
            performed_on=date(2026, 10, 7),
            parent_experiment_id=base.parent_experiment_id,
            raw_note="#022과 같은 조건",
            condition_block=ConditionBlock.model_validate(
                base.condition_block.model_dump(exclude_none=True)
            ),
        ),
    )
    for ds in eln.list_datasets(session, base.id):
        eln.create_dataset(
            session,
            rerun.id,
            DatasetCreate(
                kind=ds.kind, filename=ds.filename, content=eln.get_dataset_content(session, ds.id)
            ),
        )
    service.run_experiment(session, rerun.id)
    pairs = records.by_operator(session).pairs
    pair = next(p for p in pairs if {p.experiment_a.code, p.experiment_b.code} == {"#022", "#022b"})
    cmp = service.compare(session, base.id, rerun.id)
    assert pair.recovery_delta_pct_points == cmp.recovery_delta_pct_points
    assert pair.days_apart == 1 and pair.condition_key_count > 0
    assert pair.significant is False  # identical data → no difference


def test_records_routes(client: TestClient) -> None:
    cond = client.get("/api/analysis/records/conditions", params={"key": "cleanup_sorbent"})
    assert cond.status_code == 200 and cond.json()["groups"]
    assert client.get("/api/analysis/records/operators").status_code == 200
    periods = client.get("/api/analysis/records/periods", params={"gap_days": 7}).json()
    assert periods["gap_days"] == 7 and periods["gaps"]
    missing = client.get("/api/analysis/records/periods", params={"project_id": [999]})
    assert missing.status_code == 404
