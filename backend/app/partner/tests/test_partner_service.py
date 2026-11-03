"""Partner service: critique storage, Claude mode + fallback, decisions, Q&A."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.audit import list_events
from app.core.errors import ImmutableRecordError, ValidationFailedError
from app.core.llm import RulesOnlyGateway
from app.partner import service
from app.partner.models import Decision
from app.partner.schemas import (
    AskRequest,
    CritiqueDraft,
    DecisionCreate,
    Finding,
    HypothesisCreate,
    ProposalChange,
)


def test_seeded_critique_records(session: Session, seeded: dict[str, int]) -> None:
    (crit,) = service.list_critiques(session, seeded["#024"])
    assert crit.engine == "rules" and crit.baseline_experiment_id == seeded["#018"]
    assert len(crit.hypothesis_ids) == 3 and len(crit.proposal_ids) >= 3
    proposals = service.list_proposals(session, seeded["project"], status="pending")
    assert {p.id for p in proposals} == set(crit.proposal_ids)
    assert all(p.origin == "ai:rules" for p in proposals)


def _grounded_claude_draft(prompt: str) -> CritiqueDraft:
    assert '"EVIDENCE"' in prompt
    return CritiqueDraft(
        summary="#024는 기준 미달이며 두 조건이 동시에 바뀌었다.",
        findings=[
            Finding(
                title="원인 혼재",
                body="흡착제와 추출 시간이 함께 바뀜",
                severity="warning",
                evidence_keys=["E1"],
            ),
        ],
        hypotheses=[],
        proposals=[],
    )


def test_claude_mode_stores_claude_critique(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    gw = fake_gateway_factory(lambda _schema, prompt: _grounded_claude_draft(prompt))
    crit = service.run_critique(session, seeded["#024"], gateway=gw)
    assert crit.engine == "claude" and crit.model == "fake-claude"
    assert crit.fallback_reason is None
    events = list_events(session, entity_type="partner.Critique", entity_id=crit.id)
    assert events[0].actor == "ai:claude"


def test_claude_ungrounded_output_falls_back_to_rules(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    def invented(_schema: type[BaseModel], _prompt: str) -> CritiqueDraft:
        return CritiqueDraft(
            summary="회수율 12.345% 관찰", findings=[], hypotheses=[], proposals=[]
        )

    crit = service.run_critique(session, seeded["#024"], gateway=fake_gateway_factory(invented))
    assert crit.engine == "rules"
    assert crit.fallback_reason is not None and "12.345" in crit.fallback_reason
    none_gw = fake_gateway_factory(lambda _s, _p: None)
    crit2 = service.run_critique(session, seeded["#024"], gateway=none_gw)
    assert crit2.engine == "rules" and "unavailable" in (crit2.fallback_reason or "")


def test_decisions_accept_modify_reject(session: Session, seeded: dict[str, int]) -> None:
    pending = service.list_proposals(session, seeded["project"], status="pending")
    a, m, r = pending[0], pending[1], pending[2]
    assert (
        service.decide(session, a.id, DecisionCreate(action="accept", rationale="타당")).status
        == "accepted"
    )
    modified = service.decide(
        session,
        m.id,
        DecisionCreate(
            action="modify",
            rationale="시간만 바꾸되 7분으로",
            modifications=[ProposalChange(key="extraction_time_min", value=7)],
        ),
    )
    assert modified.status == "modified" and modified.decision is not None
    assert modified.decision.modifications[0].value == 7
    assert (
        service.decide(
            session, r.id, DecisionCreate(action="reject", rationale="우선순위 낮음")
        ).status
        == "rejected"
    )
    with pytest.raises(ValidationFailedError, match="already decided"):
        service.decide(session, a.id, DecisionCreate(action="reject", rationale="x"))
    actions = {e.action for e in list_events(session, entity_type="partner.Decision")}
    assert actions == {"decision.accept", "decision.modify", "decision.reject"}
    session.commit()
    row = session.get(Decision, a.decision.id if a.decision else 1)
    assert row is not None
    row.rationale = "rewritten"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_decision_schema_rules() -> None:
    with pytest.raises(ValidationError):
        DecisionCreate(action="modify", rationale="x")
    with pytest.raises(ValidationError):
        DecisionCreate(
            action="accept", rationale="x", modifications=[ProposalChange(key="k", value=1)]
        )
    with pytest.raises(ValidationError):
        DecisionCreate(action="accept", rationale="")


def test_user_hypothesis(session: Session, seeded: dict[str, int]) -> None:
    h = service.create_hypothesis(
        session,
        HypothesisCreate(
            project_id=seeded["project"],
            experiment_id=seeded["#024"],
            statement="GCB 양을 줄이면 회복된다",
        ),
    )
    assert h.origin == "user" and h.status == "open"
    assert h.id in {x.id for x in service.list_hypotheses(session, seeded["project"])}


def test_ask_routes_topics_to_evidence(session: Session, seeded: dict[str, int]) -> None:
    rules = RulesOnlyGateway()
    ans = service.ask(
        session,
        AskRequest(
            project_id=seeded["project"],
            experiment_id=seeded["#024"],
            question="IS 억제와 매트릭스 효과 관계는?",
        ),
        gateway=rules,
    )
    assert set(ans.topics) >= {"internal_standard", "matrix_effect"}
    assert ans.evidence and all(f"[{e.key}]" in ans.answer for e in ans.evidence)
    no_exp = service.ask(
        session, AskRequest(project_id=seeded["project"], question="요약"), gateway=rules
    )
    assert no_exp.evidence == [] and "7건" in no_exp.answer


def test_mode_reporting(fake_gateway_factory) -> None:
    assert service.get_mode(RulesOnlyGateway()).mode == "rules"
    claude = service.get_mode(fake_gateway_factory(lambda _s, _p: None))
    assert claude.mode == "claude" and claude.model == "fake-claude"
