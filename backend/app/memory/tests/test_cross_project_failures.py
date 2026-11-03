"""Cross-project search/recall and the failure archive (types, repeat patterns)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, ExperimentCreate, ExperimentOut, ProjectCreate
from app.memory import ports, service
from app.memory.schemas import FactProvider, QCFact, ResultFact, SourceRef


def _second_project(session: Session) -> tuple[int, ExperimentOut]:
    project = eln.create_project(session, ProjectCreate(name="유기산 정량", objective="교차 회상"))
    exp = eln.create_experiment(
        session,
        project.id,
        ExperimentCreate(
            code="#OA01",
            title="농약 SOP의 GCB 정제를 그대로 적용",
            author="김연구",
            performed_on=date(2026, 10, 25),
            raw_note="GCB 정제 후 유기산 피크가 작다.",
            condition_block=ConditionBlock.model_validate({"cleanup_sorbent": "GCB 7.5 mg"}),
        ),
    )
    session.commit()
    return project.id, exp


def test_search_all_spans_projects_and_labels_each_hit(
    session: Session, seeded: dict[str, int]
) -> None:
    other, exp = _second_project(session)
    hits = service.search_all(session, "GCB")
    by_project = {h.project_id for h in hits}
    assert by_project == {seeded["project"], other}
    assert any(h.experiment_id == exp.id and h.project_id == other for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    # per-project search now also says which project a hit belongs to
    assert {h.project_id for h in service.search(session, seeded["project"], "GCB")} == {
        seeded["project"]
    }
    only = service.search_all(session, "GCB", project_ids=[other])
    assert only and {h.project_id for h in only} == {other}
    with pytest.raises(NotFoundError):
        service.search_all(session, "GCB", project_ids=[9999])


def test_recall_all_merges_projects(session: Session, seeded: dict[str, int]) -> None:
    other, exp = _second_project(session)
    bundle = service.recall_all(session, "GCB")
    assert bundle.project_ids == [seeded["project"], other]
    projects = {x.experiment.project_id for x in bundle.experiments}
    assert projects == {seeded["project"], other}
    assert exp.id in {x.experiment.id for x in bundle.experiments}
    gcb = next(t for t in bundle.terms if t.term == "gcb")
    assert gcb.facet == "condition"
    assert all(
        h.project_id == x.experiment.project_id for x in bundle.experiments for h in x.reasons
    )
    single = service.recall(session, seeded["project"], "GCB")
    assert single.project_ids == [seeded["project"]]


def test_cross_project_routes(client: TestClient) -> None:
    hits = client.get("/api/memory/search", params={"q": "GCB"}).json()
    assert hits and all("project_id" in h for h in hits)
    bundle = client.get("/api/memory/recall", params={"q": "GCB", "project_id": [1]}).json()
    assert bundle["project_ids"] == [1]
    assert (
        client.get("/api/memory/recall", params={"q": "GCB", "project_id": [99]}).status_code == 404
    )
    archive = client.get("/api/memory/failures").json()
    assert archive["failure_count"] == len(archive["failures"])


# ----------------------------------------------------------- failure archive


class _FakeQC(FactProvider):
    """Stored QC stand-in: critical recovery flags for the listed analytes."""

    name = "fake-qc"

    def __init__(self, failing: dict[int, list[str]], analyzed: set[int]) -> None:
        self.failing = failing
        self.analyzed = analyzed

    def _src(self, experiment_id: int) -> SourceRef:
        return SourceRef(
            ref_type="analysis.AnalysisResult",
            ref_id=experiment_id,
            field="flags",
            experiment_id=experiment_id,
        )

    def results(self, session: Session, experiment_id: int) -> list[ResultFact]:
        if experiment_id not in self.analyzed:
            return []
        value = 50.0 if experiment_id in self.failing else 90.0
        return [
            ResultFact(
                metric="recovery_mean_pct",
                label="평균 회수율",
                value=value,
                unit="%",
                source=self._src(experiment_id),
            )
        ]

    def qc_flags(self, session: Session, experiment_id: int) -> list[QCFact] | None:
        return [
            QCFact(
                code="recovery_out_of_range",
                severity="critical",
                analyte=a,
                value=50.0,
                source=self._src(experiment_id),
            )
            for a in self.failing.get(experiment_id, [])
        ]


def _child(
    session: Session, parent: ExperimentOut, code: str, day: int, **cond: object
) -> ExperimentOut:
    base = parent.condition_block.model_dump(exclude_none=True) | cond
    return eln.create_experiment(
        session,
        parent.project_id,
        ExperimentCreate(
            code=code,
            title=code,
            author="테스트",
            performed_on=date(2026, 11, day),
            parent_experiment_id=parent.id,
            raw_note="기록",
            condition_block=ConditionBlock.model_validate(base),
        ),
    )


@pytest.fixture
def lineage(session: Session, no_providers: None) -> Iterator[dict[str, ExperimentOut]]:
    """root → A (sorbent X, fails c1) → B (retry, fails c1) → C (passes);
    root → D (same sorbent X again, fails c1); root → E (other change, fails c2)."""
    project = eln.create_project(session, ProjectCreate(name="실패 아카이브"))
    root = eln.create_experiment(
        session,
        project.id,
        ExperimentCreate(
            code="#R",
            title="기준",
            author="테스트",
            performed_on=date(2026, 11, 1),
            raw_note="기준",
            condition_block=ConditionBlock.model_validate(
                {"cleanup_sorbent": "C18", "extraction_time_min": 10}
            ),
        ),
    )
    a = _child(session, root, "#A", 2, cleanup_sorbent="X")
    b = _child(session, a, "#B", 3)
    c = _child(session, b, "#C", 4, extraction_time_min=12)
    d = _child(session, root, "#D", 5, cleanup_sorbent="X")
    e = _child(session, root, "#E", 6, extraction_time_min=5, cleanup_sorbent="Y")
    session.commit()
    exps = {x.code: x for x in (root, a, b, c, d, e)}
    failing = {a.id: ["c1"], b.id: ["c1"], d.id: ["c1", "c3"], e.id: ["c2"]}
    ports.register(_FakeQC(failing, analyzed={x.id for x in exps.values()}))
    yield exps
    ports.unregister("fake-qc")


def test_failure_types_are_exclusive_and_counted(
    session: Session, lineage: dict[str, ExperimentOut]
) -> None:
    pid = lineage["#R"].project_id
    archive = service.failure_archive(session, [pid])
    assert archive.experiment_count == 6 and archive.analyzed_count == 6
    assert archive.failure_count == 4
    assert [f.experiment.code for f in archive.failures] == ["#E", "#D", "#B", "#A"]  # newest first
    types = {t.id: t for t in archive.types}
    assert types["change:cleanup_sorbent"].count == 2  # #A and #D
    assert types["no_change"].experiment_ids == [lineage["#B"].id]
    assert types["multi_change"].experiment_ids == [lineage["#E"].id]
    assert sum(t.count for t in archive.types) == archive.failure_count
    b = next(f for f in archive.failures if f.experiment.code == "#B")
    assert b.parent_failed and b.failed_analytes == ["c1"] and b.changes == []
    assert b.recovery is not None and b.recovery.value == 50.0  # copied from the port


def test_repeat_pattern_links_retry_and_same_condition_with_resolution(
    session: Session, lineage: dict[str, ExperimentOut]
) -> None:
    archive = service.failure_archive(session, [lineage["#R"].project_id])
    assert len(archive.patterns) == 1
    p = archive.patterns[0]
    assert p.codes == ["#A", "#B", "#D"]  # #E missed another analyte: not the same failure
    assert p.shared_analytes == ["c1"]
    kinds = {(x.kind, x.from_experiment_id, x.to_experiment_id) for x in p.links}
    assert ("retry", lineage["#A"].id, lineage["#B"].id) in kinds
    assert ("same_condition", lineage["#A"].id, lineage["#D"].id) in kinds
    same = next(x for x in p.links if x.kind == "same_condition")
    assert same.key == "cleanup_sorbent" and same.value == "X"
    assert p.resolution is not None and p.resolution.code == "#C"
    assert p.resolution_qc == "pass"
    assert [c.key for c in p.resolution_changes] == ["extraction_time_min"]


def test_archive_without_qc_facts_is_empty(
    session: Session, seeded: dict[str, int], no_providers: None
) -> None:
    archive = service.failure_archive(session)
    assert archive.failure_count == 0 and archive.patterns == [] and archive.types == []
    assert archive.analyzed_count == 0
