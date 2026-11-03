"""Rule-based failure causes, linked decisions and Critic precedents (reference seed)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, DatasetCreate, ExperimentCreate
from app.partner import failures, service
from app.partner.schemas import DecisionCreate, ProposalChange
from app.wiring import install


@pytest.fixture(autouse=True)
def _providers() -> Iterator[None]:
    """Memory's failure archive reads stored QC through the fact ports."""
    install()
    yield


def _rerun(session: Session, source_id: int, code: str, day: date, **cond: object) -> int:
    """New child of ``source``'s parent with ``source``'s datasets and conditions (+ overrides)."""
    src = eln.get_experiment(session, source_id)
    exp = eln.create_experiment(
        session,
        src.project_id,
        ExperimentCreate(
            code=code,
            title=f"{code} 재시도",
            author="이분석",
            performed_on=day,
            parent_experiment_id=src.parent_experiment_id,
            raw_note="새 MgSO4 lot 개봉해 사용.",
            condition_block=ConditionBlock.model_validate(
                src.condition_block.model_dump(exclude_none=True) | cond
            ),
        ),
    )
    for ds in eln.list_datasets(session, src.id):
        content = eln.get_dataset_content(session, ds.id)
        eln.create_dataset(
            session, exp.id, DatasetCreate(kind=ds.kind, filename=ds.filename, content=content)
        )
    analysis.run_experiment(session, exp.id)
    session.commit()
    return exp.id


def test_failure_archive_explains_024_with_its_evidence(
    session: Session, seeded: dict[str, int]
) -> None:
    out = failures.failure_archive(session)
    assert [f.experiment.code for f in out.archive.failures] == ["#024"]
    exp = next(e for e in out.explanations if e.experiment_id == seeded["#024"])
    rules = [c.rule for c in exp.causes]
    assert rules[0] == "confounded_change"  # two keys changed at once
    changed = [c for c in exp.causes if c.rule == "changed_condition"]
    assert len(changed) == 2
    assert all(c.experiment_ids == [seeded["#018"], seeded["#024"]] for c in changed)
    assert any("정제 흡착제" in c.statement for c in changed)
    assert exp.hypotheses  # the seeded #024 critique stored hypotheses
    assert exp.decisions == []  # reference seed decides nothing


def test_decisions_and_follow_up_are_linked(session: Session, seeded: dict[str, int]) -> None:
    proposals = service.list_proposals(session, seeded["project"], experiment_id=seeded["#024"])
    target = next(
        p for p in proposals if p.design and p.design.template_id == "factorial_pretreatment"
    )
    value = 5.0
    service.decide(
        session,
        target.id,
        DecisionCreate(
            action="modify",
            rationale="단독 영향 확인",
            modifications=[ProposalChange(key="extraction_time_min", value=value)],
        ),
    )
    follow = _rerun(session, seeded["#018"], "#025", date(2026, 10, 22), extraction_time_min=value)
    out = failures.failure_archive(session)
    exp = next(e for e in out.explanations if e.experiment_id == seeded["#024"])
    link = next(d for d in exp.decisions if d.proposal_id == target.id)
    assert link.action == "modify" and link.rationale == "단독 영향 확인"
    assert [c.key for c in link.changes] == ["extraction_time_min"]  # the modification applies
    assert link.follow_up is not None and link.follow_up.experiment_id == follow
    m = analysis.get_metrics(session, follow)
    assert link.follow_up.recovery_mean_pct == m.recovery_mean_pct  # copied


def test_precedents_find_the_earlier_same_symptom_failure(
    session: Session, seeded: dict[str, int]
) -> None:
    # nothing failed before #024 → the Critic shows no precedent area
    first = failures.precedents(session, seeded["#024"])
    assert first.failed and first.cases == []
    assert set(first.changed_keys) == {"cleanup_sorbent", "extraction_time_min"}
    # a later GCB-only repeat (#024's data, only the sorbent changed) → #024 is its precedent
    base_time = eln.get_experiment(session, seeded["#018"]).condition_block.extraction_time_min
    later = _rerun(
        session, seeded["#024"], "#026", date(2026, 10, 23), extraction_time_min=base_time
    )
    found = failures.precedents(session, later)
    assert found.failed
    assert [c.experiment.code for c in found.cases] == ["#024"]
    case = found.cases[0]
    assert {m.kind for m in case.matches} == {"same_value", "same_analytes"}
    assert case.score == 4
    assert case.recovery_mean_pct == analysis.get_metrics(session, seeded["#024"]).recovery_mean_pct
    # a passing experiment has no symptom to look up
    assert failures.precedents(session, seeded["#018"]).cases == []
    assert failures.precedents(session, seeded["#018"]).failed is False


def test_outside_condition_block_and_note_rules(session: Session, seeded: dict[str, int]) -> None:
    # same conditions as the failed #024 → reproduction failure explained outside the block
    same = _rerun(session, seeded["#024"], "#024r", date(2026, 10, 24))
    eln_exp = eln.get_experiment(session, same)
    assert eln_exp.parent_experiment_id == seeded["#018"]
    out = failures.failure_archive(session)
    exp = next(e for e in out.explanations if e.experiment_id == same)
    note = next(c for c in exp.causes if c.rule == "note_reagent")
    assert note.note_excerpt is not None and "lot" in note.note_excerpt
    assert note.experiment_ids == [same]
    assert any(c.rule == "operator_change" for c in exp.causes)  # 김연구 → 이분석
    repeated = [c for c in exp.causes if c.rule == "repeated_value"]
    assert repeated and all(seeded["#024"] in c.experiment_ids for c in repeated)


def test_routes(client: TestClient) -> None:
    archive = client.get("/api/partner/failure-archive").json()
    assert archive["archive"]["failure_count"] == len(archive["explanations"])
    assert client.get("/api/partner/experiments/7/precedents").status_code == 200
    assert client.get("/api/partner/experiments/999/precedents").status_code == 404
