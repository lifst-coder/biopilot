"""Claude mode (FakeGateway): same schemas, validation and automatic rules fallback."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.llm import RulesOnlyGateway
from app.partner import service
from app.partner.context import build_context
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.schemas import (
    AnswerStatement,
    AskDraft,
    AskRequest,
    CritiqueDraft,
    DecisionCreate,
    ExperimentDesign,
    Finding,
    ProposalChange,
    ProposalDraft,
)


def _draft_with(proposal: ProposalDraft) -> CritiqueDraft:
    return CritiqueDraft(
        summary="#024 검토",
        findings=[Finding(title="t", body="b", severity="info", evidence_keys=["E1"])],
        hypotheses=[],
        proposals=[proposal],
    )


def test_claude_critique_uses_full_schema(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    rules_draft = RulesCritiqueEngine().critique(build_context(session, seeded["#024"]))
    gw = fake_gateway_factory(lambda _s, _p: rules_draft)
    crit = service.run_critique(session, seeded["#024"], gateway=gw)
    assert crit.engine == "claude" and crit.assessments[0].verdict == "indeterminate"
    prompt = gw.calls[0]["prompt"]
    assert "DECISION_HISTORY" in prompt and "MATRIX_EFFECT_PROTOCOL_CHANGES" in prompt
    # pending proposals with the same signature are reused, not duplicated
    assert set(crit.proposal_ids) == set(
        service.list_critiques(session, seeded["#024"])[1].proposal_ids
    )


def test_claude_repeating_a_rejected_proposal_falls_back(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    pending = service.list_proposals(session, seeded["project"], experiment_id=seeded["#024"])
    rejected = pending[0]
    service.decide(session, rejected.id, DecisionCreate(action="reject", rationale="블랭크 없음"))
    repeat = ProposalDraft(
        title="같은 제안", description="d", changes=rejected.changes, evidence_keys=[]
    )
    crit = service.run_critique(
        session, seeded["#024"], gateway=fake_gateway_factory(lambda _s, _p: _draft_with(repeat))
    )
    assert crit.engine == "rules" and "repeats decided proposal" in (crit.fallback_reason or "")


def test_claude_invalid_design_falls_back(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    bad_reps = ProposalDraft(
        title="새 설계",
        description="d",
        changes=[ProposalChange(key="x", value="y")],
        evidence_keys=[],
        design=ExperimentDesign(objective="o", replicates=17),
    )
    crit = service.run_critique(
        session, seeded["#024"], gateway=fake_gateway_factory(lambda _s, _p: _draft_with(bad_reps))
    )
    assert crit.engine == "rules" and "17" in (crit.fallback_reason or "")
    bad_exp = bad_reps.model_copy(update={"design": None, "base_experiment_id": 999})
    crit = service.run_critique(
        session, seeded["#024"], gateway=fake_gateway_factory(lambda _s, _p: _draft_with(bad_exp))
    )
    assert "unknown experiment ids" in (crit.fallback_reason or "")


def test_claude_calibration_type_outside_domain_falls_back(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    """ISSUES P1-2: ``calibration_type`` is solvent | matrix-matched | standard-addition."""
    mixed = ProposalDraft(
        title="두 곡선 비교",
        description="d",
        changes=[ProposalChange(key="calibration_type", value="solvent + matrix-matched")],
        evidence_keys=[],
    )
    crit = service.run_critique(
        session, seeded["#024"], gateway=fake_gateway_factory(lambda _s, _p: _draft_with(mixed))
    )
    assert crit.engine == "rules"
    assert "outside contract domain: calibration_type=solvent + matrix-matched" in (
        crit.fallback_reason or ""
    )
    for p in (service.get_proposal(session, i) for i in crit.proposal_ids):
        assert not [c for c in p.changes if c.key == "calibration_type"] or all(
            c.value in {"solvent", "matrix-matched", "standard-addition"}
            for c in p.changes
            if c.key == "calibration_type"
        )


def test_claude_project_critique(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    def respond(_schema: type[BaseModel], prompt: str) -> CritiqueDraft:
        assert "whole project" in prompt
        return CritiqueDraft(summary="프로젝트 검토", findings=[], hypotheses=[], proposals=[])

    crit = service.run_project_critique(
        session, seeded["project"], gateway=fake_gateway_factory(respond)
    )
    assert crit.engine == "claude" and crit.scope == "project"


def test_claude_ask_valid_answer(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    ctx = build_context(session, seeded["#024"])
    mean = ctx.evidence.get("recovery_mean")
    assert mean is not None

    def respond(schema: type[BaseModel], _prompt: str) -> BaseModel | None:
        if schema is AskDraft:
            return AskDraft(
                answer="",
                statements=[
                    AnswerStatement(
                        text=f"평균 회수율은 {mean.value:.1f}%다",
                        kind="fact",
                        evidence_keys=[mean.key],
                    ),
                    AnswerStatement(text="GCB 흡착이 원인일 것", kind="inference"),
                ],
            )
        return None  # critique → rules fallback

    ans = service.ask(
        session,
        AskRequest(project_id=seeded["project"], experiment_id=seeded["#024"], question="회수율?"),
        gateway=fake_gateway_factory(respond),
    )
    assert ans.engine == "claude" and ans.fallback_reason is None
    assert [s.kind for s in ans.statements] == ["fact", "estimate"]  # no evidence → 추정
    assert "[추정] GCB 흡착이 원인일 것" in ans.answer and ans.evidence == [mean]
    plain = service.ask(
        session,
        AskRequest(project_id=seeded["project"], experiment_id=seeded["#024"], question="IS?"),
        gateway=fake_gateway_factory(
            lambda s, _p: (
                AskDraft(answer="IS 이탈 있음", evidence_keys=["E18"]) if s is AskDraft else None
            )
        ),
    )
    assert plain.engine == "claude" and plain.statements[0].kind == "inference"


def test_claude_ask_fallbacks(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    req = AskRequest(
        project_id=seeded["project"], experiment_id=seeded["#024"], question="#024 왜 낮나"
    )
    invented = fake_gateway_factory(
        lambda s, _p: AskDraft(answer="회수율 12.3%", evidence_keys=[]) if s is AskDraft else None
    )
    ans = service.ask(session, req, gateway=invented)
    assert ans.engine == "rules" and "12.3" in (ans.fallback_reason or "")
    unknown = fake_gateway_factory(
        lambda s, _p: AskDraft(answer="x", evidence_keys=["E999"]) if s is AskDraft else None
    )
    assert "unknown evidence keys" in (
        service.ask(session, req, gateway=unknown).fallback_reason or ""
    )
    none = fake_gateway_factory(lambda _s, _p: None)
    assert service.ask(session, req, gateway=none).fallback_reason == "Claude unavailable"


def test_rules_gateway_reports_rules() -> None:
    assert service.get_mode(RulesOnlyGateway()).description.startswith("오프라인")


def test_claude_restating_a_rejected_proposal_falls_back(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    """ISSUES P1-8: exact-signature matching let a respelled value slip through."""
    pending = service.list_proposals(session, seeded["project"], experiment_id=seeded["#024"])
    rejected = next(p for p in pending if p.design and p.design.template_id == "pre_post_spike")
    service.decide(session, rejected.id, DecisionCreate(action="reject", rationale="블랭크 없음"))
    restated = ProposalDraft(
        title="전후 첨가",
        description="d",
        changes=[
            ProposalChange(key=c.key.upper(), value=str(c.value).replace(" + ", "+"))
            for c in rejected.changes
        ],
        evidence_keys=[],
    )
    crit = service.run_critique(
        session,
        seeded["#024"],
        gateway=fake_gateway_factory(lambda _s, _p: _draft_with(restated)),
    )
    assert crit.engine == "rules" and "repeats decided proposal" in (crit.fallback_reason or "")
