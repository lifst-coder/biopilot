"""Partner service: critique runs, hypotheses, proposals, decisions and Q&A.

Reads other modules only through :mod:`app.partner.context` (service interfaces).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.llm import LLMGateway, get_gateway
from app.eln import service as eln
from app.partner.context import (
    CritiqueContext,
    build_context,
    ungrounded_numbers,
    unknown_evidence_keys,
)
from app.partner.engines.claude import ClaudeCritiqueEngine
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.models import Critique, Decision, Hypothesis, Proposal
from app.partner.schemas import (
    AskRequest,
    AskResponse,
    CritiqueDraft,
    CritiqueOut,
    DecisionCreate,
    DecisionOut,
    Evidence,
    Finding,
    HypothesisCreate,
    HypothesisOut,
    PartnerMode,
    ProposalChange,
    ProposalOut,
)

# -------------------------------------------------------------------- mode


def get_mode(gateway: LLMGateway | None = None) -> PartnerMode:
    gw = gateway or get_gateway()
    if gw.mode == "claude":
        return PartnerMode(
            mode="claude",
            model=gw.model_name,
            description="Claude 생성 모드 — 실패·근거 불일치 시 규칙 모드로 자동 대체",
        )
    return PartnerMode(
        mode="rules", model=None, description="오프라인 규칙 모드 (ANTHROPIC_API_KEY 미설정)"
    )


# ---------------------------------------------------------------- critique


def _validate_draft(draft: CritiqueDraft, ctx: CritiqueContext) -> str | None:
    """Return a reason string if the draft is not grounded, else ``None``."""
    unknown = unknown_evidence_keys(draft, ctx)
    if unknown:
        return f"unknown evidence keys: {', '.join(unknown)}"
    bad = ungrounded_numbers(draft, ctx)
    if bad:
        return f"ungrounded numbers: {', '.join(sorted(set(bad))[:10])}"
    return None


def _critique_out(session: Session, row: Critique) -> CritiqueOut:
    hyp_ids = session.scalars(
        select(Hypothesis.id).where(Hypothesis.critique_id == row.id).order_by(Hypothesis.id)
    ).all()
    prop_ids = session.scalars(
        select(Proposal.id).where(Proposal.critique_id == row.id).order_by(Proposal.id)
    ).all()
    return CritiqueOut(
        id=row.id,
        experiment_id=row.experiment_id,
        baseline_experiment_id=row.baseline_experiment_id,
        engine=row.engine,
        model=row.model,
        fallback_reason=row.fallback_reason,
        summary=row.summary,
        findings=[Finding.model_validate(f) for f in row.findings],
        evidence=[Evidence.model_validate(e) for e in row.evidence],
        hypothesis_ids=list(hyp_ids),
        proposal_ids=list(prop_ids),
        created_at=row.created_at,
    )


def run_critique(
    session: Session, experiment_id: int, *, gateway: LLMGateway | None = None
) -> CritiqueOut:
    """Critique an experiment and store critique, hypotheses and proposals."""
    gw = gateway or get_gateway()
    ctx = build_context(session, experiment_id)
    draft: CritiqueDraft | None = None
    engine, fallback_reason = "rules", None
    if gw.mode == "claude":
        draft = ClaudeCritiqueEngine(gw).critique(ctx)
        if draft is None:
            fallback_reason = "Claude unavailable or returned invalid output"
        elif (reason := _validate_draft(draft, ctx)) is not None:
            fallback_reason, draft = reason, None
        else:
            engine = "claude"
    if draft is None:
        draft = RulesCritiqueEngine().critique(ctx)
    actor: Actor = "ai:claude" if engine == "claude" else "ai:rules"
    project_id = ctx.experiment.project_id

    row = Critique(
        experiment_id=experiment_id,
        baseline_experiment_id=ctx.baseline.id if ctx.baseline else None,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        fallback_reason=fallback_reason,
        summary=draft.summary,
        findings=[f.model_dump(mode="json") for f in draft.findings],
        evidence=[e.model_dump(mode="json") for e in ctx.evidence.items],
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="partner.critique",
        entity_type="partner.Critique",
        entity_id=row.id,
        project_id=project_id,
        payload={"experiment_id": experiment_id, "engine": engine, "fallback": fallback_reason},
    )
    hyp_rows: list[Hypothesis] = []
    for h in draft.hypotheses:
        hyp = Hypothesis(
            project_id=project_id,
            experiment_id=experiment_id,
            critique_id=row.id,
            statement=h.statement,
            rationale=h.rationale,
            status="proposed",
            origin=actor,
            evidence_keys=h.evidence_keys,
        )
        session.add(hyp)
        session.flush()
        hyp_rows.append(hyp)
        record_event(
            session,
            actor=actor,
            action="create",
            entity_type="partner.Hypothesis",
            entity_id=hyp.id,
            project_id=project_id,
            payload={"critique_id": row.id},
        )
    for p in draft.proposals:
        hyp_id = (
            hyp_rows[p.hypothesis_index].id
            if p.hypothesis_index is not None and 0 <= p.hypothesis_index < len(hyp_rows)
            else None
        )
        prop = Proposal(
            project_id=project_id,
            experiment_id=experiment_id,
            critique_id=row.id,
            hypothesis_id=hyp_id,
            title=p.title,
            description=p.description,
            changes=[c.model_dump(mode="json") for c in p.changes],
            evidence_keys=p.evidence_keys,
            status="pending",
            origin=actor,
        )
        session.add(prop)
        session.flush()
        record_event(
            session,
            actor=actor,
            action="create",
            entity_type="partner.Proposal",
            entity_id=prop.id,
            project_id=project_id,
            payload={"critique_id": row.id},
        )
    return _critique_out(session, row)


def get_critique(session: Session, critique_id: int) -> CritiqueOut:
    row = session.get(Critique, critique_id)
    if row is None:
        raise NotFoundError(f"Critique {critique_id} not found")
    return _critique_out(session, row)


def list_critiques(session: Session, experiment_id: int) -> list[CritiqueOut]:
    """Critiques for one experiment, newest first."""
    eln.get_experiment(session, experiment_id)
    rows = session.scalars(
        select(Critique).where(Critique.experiment_id == experiment_id).order_by(Critique.id.desc())
    )
    return [_critique_out(session, r) for r in rows]


# -------------------------------------------------------------- hypotheses


def list_hypotheses(
    session: Session, project_id: int, experiment_id: int | None = None
) -> list[HypothesisOut]:
    eln.get_project(session, project_id)
    stmt = select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)
    if experiment_id is not None:
        stmt = stmt.where(Hypothesis.experiment_id == experiment_id)
    return [HypothesisOut.model_validate(h) for h in session.scalars(stmt)]


def create_hypothesis(session: Session, data: HypothesisCreate) -> HypothesisOut:
    """Researcher-authored hypothesis (origin ``user``)."""
    eln.get_project(session, data.project_id)
    if data.experiment_id is not None:
        exp = eln.get_experiment(session, data.experiment_id)
        if exp.project_id != data.project_id:
            raise ValidationFailedError("experiment belongs to another project")
    hyp = Hypothesis(
        project_id=data.project_id,
        experiment_id=data.experiment_id,
        critique_id=None,
        statement=data.statement,
        rationale=data.rationale,
        status="open",
        origin="user",
        evidence_keys=[],
    )
    session.add(hyp)
    session.flush()
    record_event(
        session,
        actor="user",
        action="create",
        entity_type="partner.Hypothesis",
        entity_id=hyp.id,
        project_id=data.project_id,
    )
    return HypothesisOut.model_validate(hyp)


# --------------------------------------------------------------- proposals


def _proposal_out(session: Session, row: Proposal) -> ProposalOut:
    decision = session.scalar(select(Decision).where(Decision.proposal_id == row.id))
    return ProposalOut(
        id=row.id,
        project_id=row.project_id,
        experiment_id=row.experiment_id,
        critique_id=row.critique_id,
        hypothesis_id=row.hypothesis_id,
        title=row.title,
        description=row.description,
        changes=[ProposalChange.model_validate(c) for c in row.changes],
        evidence_keys=row.evidence_keys,
        status=row.status,
        origin=row.origin,
        decision=DecisionOut.model_validate(decision) if decision else None,
        created_at=row.created_at,
    )


def list_proposals(
    session: Session,
    project_id: int,
    *,
    experiment_id: int | None = None,
    status: str | None = None,
) -> list[ProposalOut]:
    eln.get_project(session, project_id)
    stmt = select(Proposal).where(Proposal.project_id == project_id).order_by(Proposal.id)
    if experiment_id is not None:
        stmt = stmt.where(Proposal.experiment_id == experiment_id)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    return [_proposal_out(session, p) for p in session.scalars(stmt)]


def get_proposal(session: Session, proposal_id: int) -> ProposalOut:
    row = session.get(Proposal, proposal_id)
    if row is None:
        raise NotFoundError(f"Proposal {proposal_id} not found")
    return _proposal_out(session, row)


_STATUS_BY_ACTION = {"accept": "accepted", "modify": "modified", "reject": "rejected"}


def decide(session: Session, proposal_id: int, data: DecisionCreate) -> ProposalOut:
    """Record the researcher's decision (once per proposal) and update proposal status."""
    row = session.get(Proposal, proposal_id)
    if row is None:
        raise NotFoundError(f"Proposal {proposal_id} not found")
    if row.status != "pending":
        raise ValidationFailedError(f"proposal already decided ({row.status})")
    decision = Decision(
        proposal_id=proposal_id,
        action=data.action,
        rationale=data.rationale,
        modifications=[m.model_dump(mode="json") for m in data.modifications],
        decided_by=data.decided_by,
    )
    session.add(decision)
    previous = row.status
    row.status = _STATUS_BY_ACTION[data.action]
    session.flush()
    record_event(
        session,
        actor="user",
        action=f"decision.{data.action}",
        entity_type="partner.Decision",
        entity_id=decision.id,
        project_id=row.project_id,
        payload={"proposal_id": proposal_id, "rationale": data.rationale},
    )
    record_event(
        session,
        actor="user",
        action="status.change",
        entity_type="partner.Proposal",
        entity_id=row.id,
        project_id=row.project_id,
        payload={"from": previous, "to": row.status},
    )
    return _proposal_out(session, row)


# --------------------------------------------------------------------- ask

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "recovery": ("회수율", "recovery"),
    "internal_standard": ("내부표준", "internal standard", "억제", "suppression"),
    "matrix_effect": ("매트릭스", "matrix"),
    "calibration": ("검량", "calibration", "r²", "r2", "가중", "weight"),
    "changes": ("변경", "차이", "diff", "비교", "바뀐", "조건"),
}
TOPIC_PREFIXES: dict[str, tuple[str, ...]] = {
    "recovery": ("recovery", "baseline_recovery", "delta:"),
    "internal_standard": ("is_",),
    "matrix_effect": ("me:",),
    "calibration": ("min_r2", "max_back_calc", "weighting:"),
    "changes": ("change:",),
}


def detect_topics(question: str) -> list[str]:
    q = question.lower()
    topics = [t for t, words in TOPIC_KEYWORDS.items() if any(w in q for w in words)]
    if re.search(r"\bis\b", q) and "internal_standard" not in topics:
        topics.append("internal_standard")
    return topics


class AskDraft(BaseModel):
    """Claude Q&A output schema (rules answers are built to the same shape)."""

    answer: str
    evidence_keys: list[str] = Field(default_factory=list)


def _fmt_ev(e: Evidence) -> str:
    if e.value is None:
        return f"- [{e.key}] {e.label}: {e.text or ''}".rstrip()
    if float(e.value).is_integer():
        value = f"{e.value:.0f}"
    elif abs(e.value) < 1:
        value = f"{e.value:.4g}"
    else:
        value = f"{e.value:.1f}"
    extra = f" ({e.text})" if e.text else ""
    return f"- [{e.key}] {e.label}: {value}{e.unit or ''}{extra}"


def ask(session: Session, data: AskRequest, *, gateway: LLMGateway | None = None) -> AskResponse:
    """Answer a question grounded in the selected experiment's evidence."""
    gw = gateway or get_gateway()
    project = eln.get_project(session, data.project_id)
    topics = detect_topics(data.question)
    if data.experiment_id is None:
        return AskResponse(
            answer=(
                f"'{project.name}' 프로젝트 실험 {project.experiment_count}건이 기록되어 있습니다. "
                "실험을 선택하면 저장된 분석 결과를 근거로 답합니다."
            ),
            engine="rules",
            evidence=[],
            topics=topics,
        )
    ctx = build_context(session, data.experiment_id)
    if ctx.experiment.project_id != data.project_id:
        raise ValidationFailedError("experiment belongs to another project")
    if gw.mode == "claude":
        prompt = f"Question: {data.question}\n\nEVIDENCE:\n" + "\n".join(
            _fmt_ev(e) for e in ctx.evidence.items
        )
        draft = gw.generate(
            system="Answer in Korean using only the EVIDENCE. Cite keys like [E2]. "
            "Do not invent numbers.",
            prompt=prompt,
            schema=AskDraft,
        )
        if draft is not None:
            probe = CritiqueDraft(summary=draft.answer, findings=[], hypotheses=[], proposals=[])
            known = {e.key: e for e in ctx.evidence.items}
            if not ungrounded_numbers(probe, ctx) and all(k in known for k in draft.evidence_keys):
                return AskResponse(
                    answer=draft.answer,
                    engine="claude",
                    evidence=[known[k] for k in draft.evidence_keys],
                    topics=topics,
                )
    prefixes = tuple(p for t in topics for p in TOPIC_PREFIXES[t])
    selected = [
        e for name, e in ctx.evidence.by_name.items() if prefixes and name.startswith(prefixes)
    ]
    if not selected:
        selected = ctx.evidence.items[:6]
        intro = f"{ctx.experiment.code}의 주요 근거입니다 (질문 주제를 특정하지 못함):"
    else:
        intro = f"{ctx.experiment.code} 관련 저장 데이터 근거입니다:"
    if not selected:
        answer = f"{ctx.experiment.code}에 저장된 분석 결과가 없습니다. 먼저 분석을 실행하세요."
    else:
        answer = "\n".join([intro, *(_fmt_ev(e) for e in selected)])
    return AskResponse(answer=answer, engine="rules", evidence=selected, topics=topics)
