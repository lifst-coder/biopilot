"""Partner service: critiques, hypotheses, proposals, decisions, decision history and Q&A.

Reads other modules through :mod:`app.partner.context` (service interfaces) plus a few
lookups on ``app.eln.service`` / ``app.analysis.service`` for validation. Every write
records an :class:`~app.core.audit.AuditEvent` in the same transaction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.grounding import GroundingIndex, base_index
from app.core.llm import LLMGateway, get_gateway
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, ExperimentCreate, ProjectOut
from app.partner import qa
from app.partner.context import (
    CritiqueContext,
    EvidenceBook,
    ProjectContext,
    build_context,
    build_project_context,
    ungrounded_numbers,
    unknown_evidence_keys,
)
from app.partner.engines.claude import ClaudeCritiqueEngine
from app.partner.engines.project import ProjectRulesEngine
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.feedback import classify_rationale, proposal_signature
from app.partner.knowledge import implementing_changes, out_of_domain_changes
from app.partner.models import (
    Critique,
    Decision,
    Hypothesis,
    HypothesisTransition,
    PartnerExchange,
    Proposal,
)
from app.partner.priority import score_proposal
from app.partner.qa import TOPIC_KEYWORDS, TOPIC_PREFIXES, detect_topics
from app.partner.schemas import (
    AnswerStatement,
    AskDraft,
    AskIntent,
    AskRequest,
    AskResponse,
    CriticAssessment,
    CritiqueDraft,
    CritiqueOut,
    CritiqueScope,
    DecisionCreate,
    DecisionFeedback,
    DecisionHistory,
    DecisionHistoryEntry,
    DecisionOut,
    Evidence,
    ExchangeHistory,
    ExchangeOut,
    ExperimentDesign,
    ExperimentDraftOut,
    Finding,
    HypothesisCreate,
    HypothesisOut,
    HypothesisStatusChange,
    HypothesisTransitionOut,
    PartnerMode,
    PriorityFactor,
    ProposalChange,
    ProposalOut,
    SourceRef,
)

__all__ = [
    "TOPIC_KEYWORDS",
    "TOPIC_PREFIXES",
    "AskDraft",
    "ask",
    "ask_stream",
    "change_hypothesis_status",
    "create_hypothesis",
    "decide",
    "decision_history",
    "detect_topics",
    "experiment_draft",
    "get_critique",
    "get_mode",
    "get_or_run_critique",
    "get_proposal",
    "list_critiques",
    "list_exchanges",
    "list_hypotheses",
    "list_project_critiques",
    "list_proposals",
    "parse_stream_text",
    "run_critique",
    "run_project_critique",
    "validate_draft",
]

# -------------------------------------------------------------------- mode


def get_mode(gateway: LLMGateway | None = None) -> PartnerMode:
    """Which engine answers right now (rules by default, Claude with an API key)."""
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


def validate_draft(draft: CritiqueDraft, ctx: CritiqueContext | ProjectContext) -> str | None:
    """Return a reason string if the draft is not grounded / repeats a decision, else ``None``."""
    unknown = unknown_evidence_keys(draft, ctx)
    if unknown:
        return f"unknown evidence keys: {', '.join(unknown)}"
    bad = ungrounded_numbers(draft, ctx)
    if bad:
        return f"ungrounded numbers: {', '.join(sorted(set(bad))[:10])}"
    out_of_domain = [bad for p in draft.proposals for bad in out_of_domain_changes(p.changes)]
    if out_of_domain:
        return f"value outside contract domain: {', '.join(out_of_domain)}"
    experiment_id = ctx.experiment.id if isinstance(ctx, CritiqueContext) else None
    repeated = [
        p.title for p in draft.proposals if ctx.decisions.repeated_by(p.changes, experiment_id)
    ]
    if repeated:
        return f"repeats decided proposal: {', '.join(repeated)}"
    experiments = (
        {e.id for e in ctx.project_experiments}
        if isinstance(ctx, CritiqueContext)
        else {e.id for e in ctx.experiments}
    )
    for p in draft.proposals:
        ids = set(p.design.basis_experiment_ids if p.design else [])
        if p.base_experiment_id is not None:
            ids.add(p.base_experiment_id)
        if ids - experiments:
            return f"unknown experiment ids in proposal '{p.title}'"
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
        project_id=row.project_id,
        scope="project" if row.scope == "project" else "experiment",
        experiment_id=row.experiment_id,
        baseline_experiment_id=row.baseline_experiment_id,
        engine="claude" if row.engine == "claude" else "rules",
        model=row.model,
        fallback_reason=row.fallback_reason,
        summary=row.summary,
        findings=[Finding.model_validate(f) for f in row.findings],
        assessments=[CriticAssessment.model_validate(a) for a in row.assessments or []],
        decision_feedback=[DecisionFeedback.model_validate(f) for f in row.decision_feedback or []],
        evidence=[Evidence.model_validate(e) for e in row.evidence],
        hypothesis_ids=list(hyp_ids),
        proposal_ids=sorted({*prop_ids, *(row.reused_proposal_ids or [])}),
        context_fingerprint=row.context_fingerprint,
        created_at=row.created_at,
    )


def _draft(
    ctx: CritiqueContext | ProjectContext, gw: LLMGateway
) -> tuple[CritiqueDraft, Literal["rules", "claude"], str | None]:
    """Claude draft when available and valid, else the rules draft (+ fallback reason)."""
    draft: CritiqueDraft | None = None
    fallback_reason: str | None = None
    if gw.mode == "claude":
        engine = ClaudeCritiqueEngine(gw)
        draft = (
            engine.critique(ctx)
            if isinstance(ctx, CritiqueContext)
            else engine.critique_project(ctx)
        )
        if draft is None:
            fallback_reason = "Claude unavailable or returned invalid output"
        elif (reason := validate_draft(draft, ctx)) is not None:
            fallback_reason, draft = reason, None
        else:
            return draft, "claude", None
    rules = (
        RulesCritiqueEngine().critique(ctx)
        if isinstance(ctx, CritiqueContext)
        else ProjectRulesEngine().critique(ctx)
    )
    return rules, "rules", fallback_reason


def _store_critique(
    session: Session,
    *,
    project_id: int,
    scope: CritiqueScope,
    experiment_id: int | None,
    baseline_id: int | None,
    draft: CritiqueDraft,
    engine: Literal["rules", "claude"],
    model: str | None,
    fallback_reason: str | None,
    evidence: list[Evidence],
    fingerprint: str,
    failing_keys: list[str],
) -> CritiqueOut:
    actor: Actor = "ai:claude" if engine == "claude" else "ai:rules"
    pending: dict[str, int] = {}
    if experiment_id is not None:
        for existing in session.scalars(
            select(Proposal).where(
                Proposal.experiment_id == experiment_id, Proposal.status == "pending"
            )
        ):
            pending.setdefault(
                existing.signature or proposal_signature(_changes(existing)), existing.id
            )
    new_props = [p for p in draft.proposals if proposal_signature(p.changes) not in pending]
    reused = sorted(
        {pending[s] for p in draft.proposals if (s := proposal_signature(p.changes)) in pending}
    )
    row = Critique(
        project_id=project_id,
        scope=scope,
        experiment_id=experiment_id,
        baseline_experiment_id=baseline_id,
        engine=engine,
        model=model,
        fallback_reason=fallback_reason,
        summary=draft.summary,
        findings=[f.model_dump(mode="json") for f in draft.findings],
        assessments=[a.model_dump(mode="json") for a in draft.assessments],
        decision_feedback=[f.model_dump(mode="json") for f in draft.decision_feedback],
        evidence=[e.model_dump(mode="json") for e in evidence],
        reused_proposal_ids=reused,
        context_fingerprint=fingerprint,
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
        payload={
            "scope": scope,
            "experiment_id": experiment_id,
            "engine": engine,
            "fallback": fallback_reason,
            "decisions_considered": [f.decision_id for f in draft.decision_feedback],
            "reused_proposal_ids": reused,
        },
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
    assessment = next(iter(draft.assessments), None)
    for pd in new_props if experiment_id is not None else []:
        hyp_id = (
            hyp_rows[pd.hypothesis_index].id
            if pd.hypothesis_index is not None and 0 <= pd.hypothesis_index < len(hyp_rows)
            else None
        )
        priority, factors = score_proposal(pd, assessment, failing_keys)
        prop = Proposal(
            project_id=project_id,
            experiment_id=experiment_id,
            critique_id=row.id,
            hypothesis_id=hyp_id,
            title=pd.title,
            description=pd.description,
            changes=[c.model_dump(mode="json") for c in pd.changes],
            evidence_keys=pd.evidence_keys,
            status="pending",
            origin=actor,
            design=pd.design.model_dump(mode="json") if pd.design else None,
            base_experiment_id=pd.base_experiment_id or experiment_id,
            priority=priority,
            priority_factors=[f.model_dump(mode="json") for f in factors],
            signature=proposal_signature(pd.changes),
            supersedes_proposal_ids=pd.supersedes_proposal_ids,
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
            payload={
                "critique_id": row.id,
                "priority": priority,
                "supersedes_proposal_ids": pd.supersedes_proposal_ids,
            },
        )
    return _critique_out(session, row)


def _failing_keys(ctx: CritiqueContext) -> list[str]:
    return [e.key for a in ctx.failing_analytes() if (e := ctx.evidence.get(f"recovery:{a}"))]


def run_critique(
    session: Session, experiment_id: int, *, gateway: LLMGateway | None = None
) -> CritiqueOut:
    """Critique an experiment and store critique, hypotheses and proposals."""
    gw = gateway or get_gateway()
    ctx = build_context(session, experiment_id)
    draft, engine, fallback_reason = _draft(ctx, gw)
    return _store_critique(
        session,
        project_id=ctx.experiment.project_id,
        scope="experiment",
        experiment_id=experiment_id,
        baseline_id=ctx.baseline.id if ctx.baseline else None,
        draft=draft,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        fallback_reason=fallback_reason,
        evidence=ctx.evidence.items,
        fingerprint=ctx.fingerprint(),
        failing_keys=_failing_keys(ctx),
    )


def get_or_run_critique(
    session: Session, experiment_id: int, *, gateway: LLMGateway | None = None
) -> tuple[CritiqueOut, bool]:
    """Latest critique if its inputs (evidence + decisions) are unchanged, else a new one.

    Returns ``(critique, reused)``. A rules critique is not reused when Claude is
    available, so switching on the API key upgrades the answer.
    """
    gw = gateway or get_gateway()
    fingerprint = build_context(session, experiment_id).fingerprint()
    latest = session.scalars(
        select(Critique)
        .where(Critique.experiment_id == experiment_id, Critique.scope == "experiment")
        .order_by(Critique.id.desc())
        .limit(1)
    ).first()
    if (
        latest is not None
        and latest.context_fingerprint == fingerprint
        and (gw.mode == "rules" or latest.engine == "claude")
    ):
        return _critique_out(session, latest), True
    return run_critique(session, experiment_id, gateway=gw), False


def run_project_critique(
    session: Session, project_id: int, *, gateway: LLMGateway | None = None
) -> CritiqueOut:
    """Project-level critique over all experiments (PAR-7, same CritiqueDraft schema)."""
    gw = gateway or get_gateway()
    ctx = build_project_context(session, project_id)
    draft, engine, fallback_reason = _draft(ctx, gw)
    draft = draft.model_copy(update={"proposals": []})
    return _store_critique(
        session,
        project_id=project_id,
        scope="project",
        experiment_id=None,
        baseline_id=None,
        draft=draft,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        fallback_reason=fallback_reason,
        evidence=ctx.evidence.items,
        fingerprint=ctx.fingerprint(),
        failing_keys=[],
    )


def get_critique(session: Session, critique_id: int) -> CritiqueOut:
    """One stored critique."""
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


def list_project_critiques(
    session: Session, project_id: int, scope: CritiqueScope | None = None
) -> list[CritiqueOut]:
    """All critiques of a project (optionally one scope), newest first."""
    eln.get_project(session, project_id)
    stmt = select(Critique).where(Critique.project_id == project_id).order_by(Critique.id.desc())
    if scope is not None:
        stmt = stmt.where(Critique.scope == scope)
    return [_critique_out(session, r) for r in session.scalars(stmt)]


# -------------------------------------------------------------- hypotheses


def _hypothesis_out(session: Session, h: Hypothesis) -> HypothesisOut:
    transitions = session.scalars(
        select(HypothesisTransition)
        .where(HypothesisTransition.hypothesis_id == h.id)
        .order_by(HypothesisTransition.id)
    )
    out = HypothesisOut.model_validate(h)
    out.transitions = [HypothesisTransitionOut.model_validate(t) for t in transitions]
    return out


def list_hypotheses(
    session: Session, project_id: int, experiment_id: int | None = None
) -> list[HypothesisOut]:
    """Hypotheses of a project (optionally one experiment), oldest first."""
    eln.get_project(session, project_id)
    stmt = select(Hypothesis).where(Hypothesis.project_id == project_id).order_by(Hypothesis.id)
    if experiment_id is not None:
        stmt = stmt.where(Hypothesis.experiment_id == experiment_id)
    return [_hypothesis_out(session, h) for h in session.scalars(stmt)]


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
    return _hypothesis_out(session, hyp)


#: Allowed hypothesis status transitions (PAR-1).
HYPOTHESIS_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"open"}),
    "open": frozenset({"supported", "refuted"}),
    "supported": frozenset(),
    "refuted": frozenset(),
}


def change_hypothesis_status(
    session: Session, hypothesis_id: int, data: HypothesisStatusChange
) -> HypothesisOut:
    """Move a hypothesis proposed → open → supported/refuted (audited, with rationale).

    ``supported``/``refuted`` require at least one AnalysisResult of the same project.
    """
    hyp = session.get(Hypothesis, hypothesis_id)
    if hyp is None:
        raise NotFoundError(f"Hypothesis {hypothesis_id} not found")
    if data.status not in HYPOTHESIS_TRANSITIONS[hyp.status]:
        raise ValidationFailedError(f"transition {hyp.status} → {data.status} is not allowed")
    if data.status in ("supported", "refuted") and not data.evidence_result_ids:
        raise ValidationFailedError(f"'{data.status}' needs at least one evidence_result_id")
    for rid in data.evidence_result_ids:
        result = analysis.get_result(session, rid)
        if eln.get_experiment(session, result.experiment_id).project_id != hyp.project_id:
            raise ValidationFailedError(f"AnalysisResult {rid} belongs to another project")
    previous = hyp.status
    transition = HypothesisTransition(
        hypothesis_id=hyp.id,
        from_status=previous,
        to_status=data.status,
        rationale=data.rationale,
        evidence_result_ids=list(data.evidence_result_ids),
        decided_by=data.decided_by,
    )
    session.add(transition)
    hyp.status = data.status
    session.flush()
    record_event(
        session,
        actor="user",
        action="status.change",
        entity_type="partner.Hypothesis",
        entity_id=hyp.id,
        project_id=hyp.project_id,
        payload={
            "from": previous,
            "to": data.status,
            "rationale": data.rationale,
            "evidence_result_ids": list(data.evidence_result_ids),
            "transition_id": transition.id,
        },
    )
    return _hypothesis_out(session, hyp)


# --------------------------------------------------------------- proposals


def _changes(row: Proposal) -> list[ProposalChange]:
    return [ProposalChange.model_validate(c) for c in row.changes]


def _decision_out(decision: Decision) -> DecisionOut:
    out = DecisionOut.model_validate(decision)
    out.reason_category, out.constraints = classify_rationale(decision.rationale)
    return out


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
        changes=_changes(row),
        evidence_keys=row.evidence_keys,
        status=row.status,
        origin=row.origin,
        decision=_decision_out(decision) if decision else None,
        design=ExperimentDesign.model_validate(row.design) if row.design else None,
        base_experiment_id=row.base_experiment_id,
        priority=row.priority or 0,
        priority_factors=[PriorityFactor.model_validate(f) for f in row.priority_factors or []],
        signature=row.signature,
        supersedes_proposal_ids=list(row.supersedes_proposal_ids or []),
        implementing_changes=implementing_changes(
            _changes(row),
            [ProposalChange.model_validate(m) for m in decision.modifications]
            if decision is not None and decision.action == "modify"
            else [],
        ),
        created_at=row.created_at,
    )


def list_proposals(
    session: Session,
    project_id: int,
    *,
    experiment_id: int | None = None,
    status: str | None = None,
    sort: Literal["id", "priority"] = "id",
) -> list[ProposalOut]:
    """Proposals of a project; ``sort="priority"`` orders by the PAR-8 score (desc)."""
    eln.get_project(session, project_id)
    stmt = select(Proposal).where(Proposal.project_id == project_id)
    if experiment_id is not None:
        stmt = stmt.where(Proposal.experiment_id == experiment_id)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    if sort == "priority":
        stmt = stmt.order_by(Proposal.priority.desc(), Proposal.id)
    else:
        stmt = stmt.order_by(Proposal.id)
    return [_proposal_out(session, p) for p in session.scalars(stmt)]


def get_proposal(session: Session, proposal_id: int) -> ProposalOut:
    """One proposal with its decision (if any)."""
    row = session.get(Proposal, proposal_id)
    if row is None:
        raise NotFoundError(f"Proposal {proposal_id} not found")
    return _proposal_out(session, row)


_STATUS_BY_ACTION = {"accept": "accepted", "modify": "modified", "reject": "rejected"}


def decide(
    session: Session, proposal_id: int, data: DecisionCreate, *, actor: Actor = "user"
) -> ProposalOut:
    """Record the researcher's decision (once per proposal) and update proposal status.

    The rationale is classified (resource constraint / scientific / priority …) and
    becomes evidence for every later critique of the project (Decision History).
    ``actor`` is the audit actor (``seed`` for a replayed lab history); ``decided_on``
    dates the decision itself and must lie between the experiment and today.
    """
    row = session.get(Proposal, proposal_id)
    if row is None:
        raise NotFoundError(f"Proposal {proposal_id} not found")
    if row.status != "pending":
        raise ValidationFailedError(f"proposal already decided ({row.status})")
    if out_of_domain := out_of_domain_changes(data.modifications):
        raise ValidationFailedError(
            "modification outside contract domain: " + ", ".join(out_of_domain)
        )
    if data.decided_on is not None:
        performed_on = eln.get_experiment(session, row.experiment_id).performed_on
        if data.decided_on < performed_on:
            raise ValidationFailedError(
                f"decided_on {data.decided_on} is before the experiment ({performed_on})"
            )
        if data.decided_on > date.today():
            raise ValidationFailedError(f"decided_on {data.decided_on} is in the future")
    decision = Decision(
        proposal_id=proposal_id,
        action=data.action,
        rationale=data.rationale,
        modifications=[m.model_dump(mode="json") for m in data.modifications],
        decided_by=data.decided_by,
        decided_on=data.decided_on,
    )
    session.add(decision)
    previous = row.status
    row.status = _STATUS_BY_ACTION[data.action]
    session.flush()
    category, constraints = classify_rationale(data.rationale)
    record_event(
        session,
        actor=actor,
        action=f"decision.{data.action}",
        entity_type="partner.Decision",
        entity_id=decision.id,
        project_id=row.project_id,
        payload={
            "proposal_id": proposal_id,
            "rationale": data.rationale,
            "reason_category": category,
            "constraints": constraints,
            "signature": row.signature,
            "decided_by": data.decided_by,
            "decided_on": data.decided_on.isoformat() if data.decided_on else None,
        },
    )
    record_event(
        session,
        actor=actor,
        action="status.change",
        entity_type="partner.Proposal",
        entity_id=row.id,
        project_id=row.project_id,
        payload={"from": previous, "to": row.status},
    )
    return _proposal_out(session, row)


def decision_history(
    session: Session, project_id: int, experiment_id: int | None = None
) -> DecisionHistory:
    """Every decision of a project with the later critiques that reflected it."""
    eln.get_project(session, project_id)
    codes = {e.id: e.code for e in eln.list_experiments(session, project_id)}
    stmt = (
        select(Decision, Proposal)
        .join(Proposal, Proposal.id == Decision.proposal_id)
        .where(Proposal.project_id == project_id)
        .order_by(Decision.id.desc())
    )
    if experiment_id is not None:
        stmt = stmt.where(Proposal.experiment_id == experiment_id)
    reflected: dict[int, list[int]] = {}
    for crit in session.scalars(select(Critique).where(Critique.project_id == project_id)):
        for fb in crit.decision_feedback or []:
            reflected.setdefault(int(fb["decision_id"]), []).append(crit.id)
    entries = [
        DecisionHistoryEntry(
            decision=_decision_out(d),
            proposal_id=p.id,
            proposal_title=p.title,
            proposal_changes=_changes(p),
            experiment_id=p.experiment_id,
            experiment_code=codes.get(p.experiment_id, str(p.experiment_id)),
            reflected_in_critique_ids=sorted(reflected.get(d.id, [])),
        )
        for d, p in session.execute(stmt).all()
    ]
    return DecisionHistory(project_id=project_id, entries=entries)


def _next_code(codes: list[str]) -> str:
    numbers = [(int(m.group(1)), len(m.group(1))) for c in codes if (m := re.search(r"(\d+)$", c))]
    if not numbers:
        return "#001"
    value, width = max(numbers)
    return f"#{value + 1:0{width}d}"


def experiment_draft(session: Session, proposal_id: int) -> ExperimentDraftOut:
    """Unsaved ``ExperimentCreate`` = base experiment conditions + proposal changes (PAR-2).

    A ``modify`` decision's modifications override the proposal's changes. Pending
    proposals return a preview (``ready=False``); rejected proposals are refused.
    """
    proposal = get_proposal(session, proposal_id)
    if proposal.status == "rejected":
        raise ValidationFailedError("rejected proposals have no experiment draft")
    base_id = proposal.base_experiment_id or proposal.experiment_id
    base = eln.get_experiment(session, base_id)
    applied: dict[str, ProposalChange] = {c.key: c for c in proposal.changes}
    notes: list[str] = []
    if proposal.decision is not None and proposal.decision.action == "modify":
        for m in proposal.decision.modifications:
            applied[m.key] = m
        notes.append("수정 결정의 modifications를 제안 변경보다 우선 적용했다.")
    if proposal.status == "pending":
        notes.append("아직 결정되지 않은 제안의 미리보기다. 수락/수정 후 ELN 화면에서 생성한다.")
    conditions: dict[str, Any] = base.condition_block.model_dump(exclude_none=True)
    for change in applied.values():
        conditions[change.key] = change.value
    try:
        block = ConditionBlock.model_validate(conditions)
    except ValidationError as exc:
        raise ValidationFailedError(
            f"proposal changes do not fit the condition block: {exc}"
        ) from exc
    design = proposal.design
    lines = [
        f"목적: {design.objective if design else proposal.description}",
        f"근거: Partner 제안 P{proposal.id} (기준 실험 {base.code})",
        "변경: " + "; ".join(f"{c.key} = {c.value}" for c in applied.values()),
    ]
    if design is not None:
        if design.variables:
            lines.append(
                "변수: "
                + "; ".join(
                    f"{v.label}({'변화' if v.role == 'varied' else '고정'})"
                    for v in design.variables
                )
            )
        if design.controls:
            lines.append("대조군: " + "; ".join(c.name for c in design.controls))
        if design.replicates is not None:
            lines.append(f"반복: 수준당 {design.replicates}회 ({design.replicates_basis or ''})")
        if design.measurements:
            lines.append("측정: " + "; ".join(design.measurements))
    lines.append("※ Partner가 만든 초안 — 원본 기록은 연구자가 실험 후 작성·확정한다.")
    codes = [e.code for e in eln.list_experiments(session, proposal.project_id)]
    draft = ExperimentCreate(
        code=_next_code(codes),
        title=proposal.title[:200],
        author="",
        performed_on=date.today(),
        parent_experiment_id=base.id,
        raw_note="\n".join(lines),
        condition_block=block,
        attachments=[],
    )
    return ExperimentDraftOut(
        proposal_id=proposal.id,
        proposal_status=proposal.status,
        ready=proposal.status in ("accepted", "modified"),
        base_experiment_id=base.id,
        base_experiment_code=base.code,
        applied_changes=list(applied.values()),
        notes=notes,
        draft=draft,
    )


# --------------------------------------------------------------------- ask

ASK_SYSTEM = (
    "Answer in Korean using only the EVIDENCE and the RULES_ANALYSIS. Return statements: "
    "kind='fact' restates evidence, 'inference' is a judgement over cited evidence, "
    "'estimate' (추정) has no direct data. Cite evidence keys on every fact/inference. "
    "Do not invent numbers. Mention recorded researcher decisions when relevant."
)
ASK_STREAM_SYSTEM = (
    "Answer in Korean, one statement per line, using only the EVIDENCE. End every line "
    "with its evidence keys like [E2][E5]. Start a line with [추정] when no evidence "
    "supports it. Do not invent numbers."
)


@runtime_checkable
class StreamingGateway(Protocol):
    """Optional gateway capability: token streaming of plain text (PAR-9)."""

    def stream_text(self, *, system: str, prompt: str) -> Iterator[str]: ...


class _Plan:
    """Resolved question: project, experiment, intent and topics."""

    def __init__(self, session: Session, data: AskRequest) -> None:
        self.project: ProjectOut = eln.get_project(session, data.project_id)
        codes = {e.code: e.id for e in eln.list_experiments(session, data.project_id)}
        self.experiment_id: int | None = data.experiment_id
        if data.experiment_id is not None:
            exp = eln.get_experiment(session, data.experiment_id)
            if exp.project_id != data.project_id:
                raise ValidationFailedError("experiment belongs to another project")
        for code in qa.mentioned_codes(data.question):
            if code in codes:
                self.experiment_id = codes[code]
                break
        self.question = data.question
        self.topics = detect_topics(data.question)
        self.intent: AskIntent = qa.detect_intent(data.question, self.experiment_id is not None)


def _rules_answer(
    session: Session, plan: _Plan, gw: LLMGateway
) -> tuple[AskResponse, list[Evidence], GroundingIndex]:
    """Deterministic answer + the evidence pool / grounding index it was built from."""
    exp_id = plan.experiment_id
    crit_gw = gw
    if plan.intent in ("cause", "next_experiment") and exp_id is not None:
        critique, reused = get_or_run_critique(session, exp_id, gateway=crit_gw)
        proposals = [
            p
            for p in list_proposals(session, plan.project.id, experiment_id=exp_id)
            if p.id in set(critique.proposal_ids)
        ]
        code = next(
            (e.label.split(" ")[0] for e in critique.evidence if e.label.startswith("#")), ""
        )
        if plan.intent == "cause":
            statements = qa.cause_statements(critique, proposals)
            intro = (
                f"{code} Research Critic 판정 (비판 #{critique.id}"
                + (", 입력 변화 없음 → 저장된 비판 재사용" if reused else "")
                + "):"
            )
        else:
            statements = [
                AnswerStatement(
                    text=f"결정 반영: {fb.note}",
                    kind="fact",
                    evidence_keys=[fb.evidence_key] if fb.evidence_key else [],
                )
                for fb in critique.decision_feedback
            ] + qa.proposal_statements(proposals)
            intro = f"{code} 후속 실험 설계 (비판 #{critique.id}, 우선순위 순):"
        pool = critique.evidence
        extra = [
            SourceRef(ref_type="partner.Critique", ref_id=critique.id, label=f"비판 #{critique.id}")
        ]
        extra += [
            SourceRef(ref_type="partner.Proposal", ref_id=p.id, label=f"P{p.id} {p.title}")
            for p in proposals
        ]
        response = _response(plan, statements, pool, intro, extra)
        response.critique_id, response.proposal_ids = critique.id, [p.id for p in proposals]
        return response, pool, _pool_index(session, plan.project.id, pool)
    if plan.intent == "decisions":
        history = decision_history(session, plan.project.id, exp_id)
        book = EvidenceBook()
        for entry in history.entries:
            book.add(
                f"decision:{entry.decision.id}",
                source="partner",
                ref_type="partner.Decision",
                ref_id=entry.decision.id,
                label=f"P{entry.proposal_id} {entry.decision.action} 사유",
                text=entry.decision.rationale,
            )
        statements = qa.decision_statements(history.entries, book.items)
        response = _response(plan, statements, book.items, "기록된 연구자 결정 (최신순):", [])
        return response, book.items, _pool_index(session, plan.project.id, book.items)
    if exp_id is None:
        pctx = build_project_context(session, plan.project.id)
        count = pctx.evidence.add(
            "experiment_count",
            source="eln",
            ref_type="eln.Project",
            ref_id=plan.project.id,
            label="기록된 실험 수",
            value=float(plan.project.experiment_count),
        )
        statements = [
            AnswerStatement(
                text=f"'{plan.project.name}' 프로젝트 실험 {plan.project.experiment_count}건이 "
                "기록되어 있다.",
                kind="fact",
                evidence_keys=[count.key],
            )
        ]
        for e in pctx.evidence.prefixed("recovery_mean:"):
            fail = pctx.evidence.get("failing:" + e.label.split(" ")[0])
            text = f"{e.label} {e.value:.1f}{e.unit or ''}" if e.value is not None else e.label
            if fail is not None:
                text += f" — 기준 미달: {fail.text}"
            statements.append(
                AnswerStatement(
                    text=text, kind="fact", evidence_keys=[e.key] + ([fail.key] if fail else [])
                )
            )
        intro = "실험을 선택하거나 질문에 실험 코드(#번호)를 쓰면 그 실험의 저장 근거로 답합니다."
        response = _response(plan, statements, pctx.evidence.items, intro, [])
        return response, pctx.evidence.items, pctx.grounding
    ctx = build_context(session, exp_id)
    prefixes = tuple(p for t in plan.topics for p in TOPIC_PREFIXES[t])
    selected = [
        e for name, e in ctx.evidence.by_name.items() if prefixes and name.startswith(prefixes)
    ]
    if not selected:
        selected = ctx.evidence.items[:6]
        intro = f"{ctx.experiment.code}의 주요 근거입니다 (질문 주제를 특정하지 못함):"
    else:
        intro = f"{ctx.experiment.code} 관련 저장 데이터 근거입니다:"
    statements = [
        AnswerStatement(
            text=qa.fmt_evidence(e)[len(f"- [{e.key}] ") :], kind="fact", evidence_keys=[e.key]
        )
        for e in selected
    ]
    if not selected:
        statements = [
            AnswerStatement(
                text=(
                    f"{ctx.experiment.code}에 저장된 분석 결과가 없습니다. 분석을 먼저 실행하세요."
                ),
                kind="estimate",
            )
        ]
    response = _response(plan, statements, ctx.evidence.items, intro, [])
    return response, ctx.evidence.items, ctx.grounding


def _pool_index(session: Session, project_id: int, pool: list[Evidence]) -> GroundingIndex:
    """Grounding index of an evidence pool plus the project's *active* QC criteria."""
    index = base_index()
    for e in pool:
        index.add_value(e.value, e.unit)
        index.add_text(e.label)
        index.add_text(e.text)
    c = analysis.get_project_criteria(session, project_id).active.criteria
    index.add_free(
        [
            c.recovery_min_pct,
            c.recovery_max_pct,
            c.rsd_max_pct,
            c.is_response_min_pct,
            c.is_response_max_pct,
            c.matrix_effect_abs_max_pct,
            c.back_calc_tolerance_pct,
            c.r_squared_min,
        ]
    )
    index.add_text(c.source)
    return index


def _response(
    plan: _Plan,
    statements: list[AnswerStatement],
    pool: list[Evidence],
    intro: str | None,
    extra_sources: list[SourceRef],
) -> AskResponse:
    labelled = qa.label(statements)
    evidence = qa.cited_evidence(labelled, pool)
    return AskResponse(
        answer=qa.render(labelled, intro),
        engine="rules",
        evidence=evidence,
        topics=plan.topics,
        intent=plan.intent,
        experiment_id=plan.experiment_id,
        statements=labelled,
        sources=qa.sources_for(evidence, extra_sources),
    )


def _ask_prompt(plan: _Plan, rules: AskResponse, pool: list[Evidence], *, stream: bool) -> str:
    payload = {
        "question": plan.question,
        "intent": plan.intent,
        "EVIDENCE": [e.model_dump(exclude_none=True) for e in pool],
        "RULES_ANALYSIS": [s.model_dump() for s in rules.statements],
    }
    head = "Answer as plain text lines." if stream else "Answer with the AskDraft schema."
    return head + "\nContext (JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _accept_claude(
    draft: AskDraft, rules: AskResponse, pool: list[Evidence], index: GroundingIndex
) -> AskResponse | str:
    """Validated Claude answer, or the reason it was rejected."""
    known = {e.key for e in pool}
    statements = draft.statements or [
        AnswerStatement(
            text=draft.answer,
            kind="inference" if draft.evidence_keys else "estimate",
            evidence_keys=draft.evidence_keys,
        )
    ]
    unknown = sorted({k for s in statements for k in s.evidence_keys} - known)
    unknown += sorted(set(draft.evidence_keys) - known)
    if unknown:
        return f"unknown evidence keys: {', '.join(sorted(set(unknown)))}"
    bad = index.ungrounded([s.text for s in statements] + [draft.answer])
    if bad:
        return f"ungrounded numbers: {', '.join(sorted(set(bad))[:10])}"
    labelled = qa.label(statements)
    evidence = qa.cited_evidence(labelled, pool)
    keep = [s for s in rules.sources if s.ref_type in ("partner.Critique", "partner.Proposal")]
    return rules.model_copy(
        update={
            "answer": qa.render(labelled),
            "engine": "claude",
            "statements": labelled,
            "evidence": evidence,
            "sources": qa.sources_for(evidence, keep),
        }
    )


def _store_exchange(session: Session, plan: _Plan, response: AskResponse) -> AskResponse:
    row = PartnerExchange(
        project_id=plan.project.id,
        experiment_id=plan.experiment_id,
        question=plan.question,
        engine=response.engine,
        response=response.model_dump(mode="json", exclude={"exchange_id"}),
        critique_id=response.critique_id,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor="ai:claude" if response.engine == "claude" else "ai:rules",
        action="partner.ask",
        entity_type="partner.PartnerExchange",
        entity_id=row.id,
        project_id=plan.project.id,
        payload={
            "experiment_id": plan.experiment_id,
            "intent": response.intent,
            "critique_id": response.critique_id,
            "fallback": response.fallback_reason,
        },
    )
    return response.model_copy(update={"exchange_id": row.id})


def ask(session: Session, data: AskRequest, *, gateway: LLMGateway | None = None) -> AskResponse:
    """Answer a project-context question with sources; unsupported claims are "추정".

    "왜" questions run (or reuse) the Research Critic; "다음 실험" questions return the
    Designer's proposals; "결정/기각" questions return the Decision History. Every
    exchange is stored (PAR-4).
    """
    gw = gateway or get_gateway()
    plan = _Plan(session, data)
    rules, pool, index = _rules_answer(session, plan, gw)
    response = rules
    if gw.mode == "claude":
        draft = gw.generate(
            system=ASK_SYSTEM, prompt=_ask_prompt(plan, rules, pool, stream=False), schema=AskDraft
        )
        if draft is None:
            response = rules.model_copy(update={"fallback_reason": "Claude unavailable"})
        else:
            accepted = _accept_claude(draft, rules, pool, index)
            response = (
                rules.model_copy(update={"fallback_reason": accepted})
                if isinstance(accepted, str)
                else accepted
            )
    return _store_exchange(session, plan, response)


_LINE_KEYS = re.compile(r"\[(E\d+)\]")


def parse_stream_text(text: str) -> AskDraft:
    """Plain-text streamed answer → AskDraft (one statement per non-empty line)."""
    statements: list[AnswerStatement] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        keys = _LINE_KEYS.findall(line)
        body = _LINE_KEYS.sub("", line).strip()
        estimate = body.startswith(qa.ESTIMATE_PREFIX.strip())
        if estimate:
            body = body[len(qa.ESTIMATE_PREFIX.strip()) :].strip()
        statements.append(
            AnswerStatement(
                text=body,
                kind="estimate" if estimate or not keys else "inference",
                evidence_keys=keys,
            )
        )
    return AskDraft(
        answer=text,
        evidence_keys=[k for s in statements for k in s.evidence_keys],
        statements=statements,
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def ask_stream(
    session: Session, data: AskRequest, *, gateway: LLMGateway | None = None
) -> Iterator[str]:
    """Server-sent events for the panel (PAR-9).

    Events: ``start`` → ``delta`` (provisional text while Claude streams, or one per
    statement in rules mode) → optional ``replace`` (validation failed; provisional
    text is discarded and the rules answer follows) → ``final`` (the full
    :class:`AskResponse`, including evidence). The ``/ask`` contract is unchanged.
    """
    gw = gateway or get_gateway()
    yield _sse("start", {"engine_candidate": gw.mode})
    if gw.mode == "claude" and isinstance(gw, StreamingGateway):
        plan = _Plan(session, data)
        rules, pool, index = _rules_answer(session, plan, gw)
        chunks: list[str] = []
        reason: str | None = None
        try:
            for chunk in gw.stream_text(
                system=ASK_STREAM_SYSTEM, prompt=_ask_prompt(plan, rules, pool, stream=True)
            ):
                chunks.append(chunk)
                yield _sse("delta", {"text": chunk, "provisional": True})
        except Exception as exc:  # any streaming failure falls back to rules
            reason = f"Claude stream failed: {type(exc).__name__}"
        response: AskResponse
        if reason is None:
            accepted = _accept_claude(parse_stream_text("".join(chunks)), rules, pool, index)
            if isinstance(accepted, str):
                reason = accepted
            else:
                response = accepted
        if reason is not None:
            yield _sse("replace", {"reason": reason})
            response = rules.model_copy(update={"fallback_reason": reason})
        response = _store_exchange(session, plan, response)
    else:
        response = ask(session, data, gateway=gw)
        for s in response.statements:
            yield _sse("delta", {"text": qa.render([s]) + "\n", "provisional": False})
    yield _sse("final", response.model_dump(mode="json"))


def list_exchanges(
    session: Session, project_id: int, experiment_id: int | None = None, limit: int = 50
) -> ExchangeHistory:
    """Stored Q&A exchanges, newest first (PAR-4)."""
    eln.get_project(session, project_id)
    stmt = (
        select(PartnerExchange)
        .where(PartnerExchange.project_id == project_id)
        .order_by(PartnerExchange.id.desc())
        .limit(limit)
    )
    if experiment_id is not None:
        stmt = stmt.where(PartnerExchange.experiment_id == experiment_id)
    items = [
        ExchangeOut(
            id=r.id,
            project_id=r.project_id,
            experiment_id=r.experiment_id,
            question=r.question,
            response=AskResponse.model_validate({**r.response, "exchange_id": r.id}),
            created_at=r.created_at,
        )
        for r in session.scalars(stmt)
    ]
    return ExchangeHistory(project_id=project_id, experiment_id=experiment_id, items=items)
