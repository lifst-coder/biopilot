"""PAR-1 hypothesis status, PAR-2 experiment drafts, PAR-4 exchanges, PAR-7 project critique."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.core.audit import list_events
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.llm import RulesOnlyGateway
from app.eln import service as eln
from app.eln.schemas import ProjectCreate
from app.partner import service
from app.partner.schemas import (
    AskRequest,
    DecisionCreate,
    HypothesisCreate,
    HypothesisStatusChange,
    ProposalChange,
)

RULES = RulesOnlyGateway()


def _result_id(session: Session, seeded: dict[str, int], code: str = "#024") -> int:
    return analysis.latest_results(session, seeded[code])["recovery"].id


# ------------------------------------------------------------------ PAR-1


def test_hypothesis_transitions(session: Session, seeded: dict[str, int]) -> None:
    hyp = service.list_hypotheses(session, seeded["project"], seeded["#024"])[0]
    assert hyp.status == "proposed"
    with pytest.raises(ValidationFailedError, match="not allowed"):
        service.change_hypothesis_status(
            session, hyp.id, HypothesisStatusChange(status="supported", rationale="x")
        )
    opened = service.change_hypothesis_status(
        session, hyp.id, HypothesisStatusChange(status="open", rationale="검증 대상")
    )
    assert opened.status == "open"
    with pytest.raises(ValidationFailedError, match="evidence_result_id"):
        service.change_hypothesis_status(
            session, hyp.id, HypothesisStatusChange(status="supported", rationale="x")
        )
    rid = _result_id(session, seeded)
    done = service.change_hypothesis_status(
        session,
        hyp.id,
        HypothesisStatusChange(status="refuted", rationale="후속 결과", evidence_result_ids=[rid]),
    )
    assert done.status == "refuted"
    assert [(t.from_status, t.to_status) for t in done.transitions] == [
        ("proposed", "open"),
        ("open", "refuted"),
    ]
    events = list_events(session, entity_type="partner.Hypothesis", entity_id=hyp.id)
    changes = [e.payload for e in events if e.action == "status.change"]
    assert {"from": "open", "to": "refuted"}.items() <= changes[0].items()
    with pytest.raises(ValidationFailedError):
        service.change_hypothesis_status(
            session, hyp.id, HypothesisStatusChange(status="open", rationale="재개")
        )
    with pytest.raises(NotFoundError):
        service.change_hypothesis_status(
            session, 9999, HypothesisStatusChange(status="open", rationale="x")
        )


def test_hypothesis_evidence_must_belong_to_project(
    session: Session, seeded: dict[str, int]
) -> None:
    other = eln.create_project(session, ProjectCreate(name="다른 프로젝트"))
    hyp = service.create_hypothesis(session, HypothesisCreate(project_id=other.id, statement="h"))
    with pytest.raises(ValidationFailedError, match="another project"):
        service.change_hypothesis_status(
            session,
            hyp.id,
            HypothesisStatusChange(
                status="supported", rationale="x", evidence_result_ids=[_result_id(session, seeded)]
            ),
        )
    with pytest.raises(ValidationFailedError, match="another project"):
        service.create_hypothesis(
            session,
            HypothesisCreate(project_id=other.id, experiment_id=seeded["#024"], statement="h"),
        )


def test_hypothesis_status_endpoint(client: TestClient) -> None:
    hid = client.get("/api/partner/hypotheses", params={"project_id": 1}).json()[0]["id"]
    ok = client.post(
        f"/api/partner/hypotheses/{hid}/status", json={"status": "open", "rationale": "r"}
    )
    assert ok.status_code == 200 and ok.json()["transitions"][0]["to_status"] == "open"
    bad = client.post(
        f"/api/partner/hypotheses/{hid}/status", json={"status": "proposed", "rationale": "r"}
    )
    assert bad.status_code == 400 and bad.json()["code"] == "validation_failed"


# ------------------------------------------------------------------ PAR-2


def test_experiment_draft_applies_changes_and_modifications(
    session: Session, seeded: dict[str, int]
) -> None:
    props = service.list_proposals(session, seeded["project"], experiment_id=seeded["#024"])
    pre = next(p for p in props if p.design and p.design.template_id == "pre_post_spike")
    preview = service.experiment_draft(session, pre.id)
    assert not preview.ready and preview.notes
    assert preview.draft.code == "#025" and preview.draft.parent_experiment_id == seeded["#024"]
    extra = preview.draft.condition_block.model_dump()
    assert extra["spike_stage"] == "pre-extraction + post-extraction"
    assert extra["extraction_time_min"] == 5  # #024 conditions kept
    assert "반복" in preview.draft.raw_note and f"P{pre.id}" in preview.draft.raw_note

    factorial = next(
        p for p in props if p.design and p.design.template_id == "factorial_pretreatment"
    )
    service.decide(
        session,
        factorial.id,
        DecisionCreate(
            action="modify",
            rationale="추출 시간만 7분으로",
            modifications=[ProposalChange(key="extraction_time_min", value=7)],
        ),
    )
    draft = service.experiment_draft(session, factorial.id)
    assert draft.ready and draft.base_experiment_code == "#018"
    assert draft.draft.condition_block.extraction_time_min == 7
    assert any("modifications" in n for n in draft.notes)
    # the draft is not stored: still 7 experiments
    assert len(eln.list_experiments(session, seeded["project"])) == 7


def test_experiment_draft_refusals(session: Session, seeded: dict[str, int]) -> None:
    props = service.list_proposals(session, seeded["project"], experiment_id=seeded["#024"])
    service.decide(session, props[0].id, DecisionCreate(action="reject", rationale="no"))
    with pytest.raises(ValidationFailedError, match="rejected"):
        service.experiment_draft(session, props[0].id)
    service.decide(
        session,
        props[1].id,
        DecisionCreate(
            action="modify",
            rationale="잘못된 값",
            modifications=[ProposalChange(key="ph", value="산성")],
        ),
    )
    with pytest.raises(ValidationFailedError, match="condition block"):
        service.experiment_draft(session, props[1].id)
    with pytest.raises(NotFoundError):
        service.experiment_draft(session, 9999)
    assert service._next_code(["A", "B"]) == "#001"
    assert service._next_code(["#009", "#010"]) == "#011"


def test_experiment_draft_endpoint(client: TestClient) -> None:
    body = client.get("/api/partner/proposals/1/experiment-draft").json()
    assert body["proposal_id"] == 1 and body["draft"]["code"] == "#025"


# ------------------------------------------------------------------ PAR-4 / ask


def test_exchanges_are_stored_and_audited(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    a = service.ask(
        session,
        AskRequest(project_id=pid, experiment_id=seeded["#024"], question="IS?"),
        gateway=RULES,
    )
    b = service.ask(session, AskRequest(project_id=pid, question="프로젝트 요약"), gateway=RULES)
    history = service.list_exchanges(session, pid)
    assert [x.id for x in history.items] == [b.exchange_id, a.exchange_id]
    only = service.list_exchanges(session, pid, seeded["#024"])
    assert [x.id for x in only.items] == [a.exchange_id]
    assert only.items[0].response.answer == a.answer
    events = list_events(session, entity_type="partner.PartnerExchange")
    assert {e.entity_id for e in events} == {a.exchange_id, b.exchange_id}


def test_ask_intents(session: Session, seeded: dict[str, int]) -> None:
    pid, exp = seeded["project"], seeded["#024"]
    nxt = service.ask(
        session,
        AskRequest(project_id=pid, experiment_id=exp, question="다음 실험 설계는?"),
        gateway=RULES,
    )
    assert nxt.intent == "next_experiment" and "가장 우선 제안" in nxt.answer
    none = service.ask(session, AskRequest(project_id=pid, question="결정 이력은?"), gateway=RULES)
    assert none.intent == "decisions" and none.statements[0].kind == "estimate"
    assert none.answer.splitlines()[1].startswith("[추정]")
    pending = service.list_proposals(session, pid, status="pending")
    service.decide(session, pending[0].id, DecisionCreate(action="reject", rationale="블랭크 없음"))
    dec = service.ask(session, AskRequest(project_id=pid, question="기각된 제안은?"), gateway=RULES)
    assert "블랭크 없음" in dec.answer and dec.evidence[0].ref_type == "partner.Decision"
    why = service.ask(session, AskRequest(project_id=pid, question="왜 낮나?"), gateway=RULES)
    assert why.intent == "project"  # no experiment → project-level answer
    unknown = service.ask(
        session,
        AskRequest(project_id=pid, experiment_id=seeded["#023"], question="날씨?"),
        gateway=RULES,
    )
    assert unknown.intent == "facts" and "특정하지 못함" in unknown.answer
    calib = service.ask(
        session,
        AskRequest(project_id=pid, experiment_id=seeded["#021"], question="왜?"),
        gateway=RULES,
    )
    assert calib.intent == "cause" and calib.critique_id is not None
    with pytest.raises(ValidationFailedError):
        other = eln.create_project(session, ProjectCreate(name="p2"))
        service.ask(
            session, AskRequest(project_id=other.id, experiment_id=exp, question="?"), gateway=RULES
        )


def test_ask_without_analysis(session: Session, seeded: dict[str, int]) -> None:
    from datetime import date

    from app.eln.schemas import ConditionBlock, ExperimentCreate

    exp = eln.create_experiment(
        session,
        seeded["project"],
        ExperimentCreate(
            code="#030",
            title="빈 실험",
            performed_on=date(2026, 9, 1),  # before the matrix-effect experiment
            raw_note="메모",
            condition_block=ConditionBlock(),
        ),
    )
    ans = service.ask(
        session,
        AskRequest(project_id=seeded["project"], experiment_id=exp.id, question="회수율?"),
        gateway=RULES,
    )
    assert ans.statements[0].kind == "estimate" and "분석을 먼저" in ans.answer
    crit = service.run_critique(session, exp.id, gateway=RULES)
    assert [f.title for f in crit.findings] == ["분석 결과 없음"]


# ------------------------------------------------------------------ PAR-7


def test_project_critique(session: Session, seeded: dict[str, int]) -> None:
    crit = service.run_project_critique(session, seeded["project"], gateway=RULES)
    assert crit.scope == "project" and crit.experiment_id is None and crit.proposal_ids == []
    top = crit.findings[0]
    assert "정제 흡착제" in top.title and "변경 실험에만 나타남" in top.title
    assert "#024" in top.body and "분리할 수 없다" in top.body
    (a,) = crit.assessments
    assert a.verdict == "indeterminate" and a.missing_controls[0].id == "single_variable"
    assert len(crit.hypothesis_ids) == 2
    assert any("용매 검량선" in f.title for f in crit.findings)
    listed = service.list_project_critiques(session, seeded["project"], scope="project")
    assert [c.id for c in listed] == [crit.id]
    assert len(service.list_project_critiques(session, seeded["project"])) == 2
    pending = service.list_proposals(session, seeded["project"], status="pending")
    service.decide(session, pending[0].id, DecisionCreate(action="reject", rationale="사유"))
    again = service.run_project_critique(session, seeded["project"], gateway=RULES)
    assert any(f.title == "연구자 결정 이력" for f in again.findings)


def test_project_critique_edge_cases(session: Session) -> None:
    empty = eln.create_project(session, ProjectCreate(name="빈 프로젝트"))
    crit = service.run_project_critique(session, empty.id, gateway=RULES)
    assert crit.findings[0].title == "프로젝트 수준 비판 근거 없음"


def test_project_critique_endpoints(client: TestClient) -> None:
    made = client.post("/api/partner/projects/1/critiques")
    assert made.status_code == 201 and made.json()["scope"] == "project"
    listed = client.get("/api/partner/projects/1/critiques", params={"scope": "project"}).json()
    assert [c["id"] for c in listed] == [made.json()["id"]]
