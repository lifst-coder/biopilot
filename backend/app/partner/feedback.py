"""Decision History feedback: researcher decisions flow back into later critiques.

A decision (accept/modify/reject + rationale) is immutable in ``partner_decisions``.
Before every critique the context loads the project's decisions as
:class:`PriorDecision` objects, registers each as ``partner.Decision`` evidence, and
the engines use them to (1) never repeat a decided proposal (same
:func:`proposal_signature`), (2) avoid designs needing a resource the rationale says
is unavailable, and (3) cite the rationale in findings and missing-control notes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.partner.knowledge import REASON_KEYWORDS, RESOURCE_KEYWORDS
from app.partner.models import Decision, Proposal
from app.partner.schemas import Evidence, ProposalChange


def _norm(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip().lower()


def proposal_signature(changes: list[ProposalChange]) -> str:
    """Order-independent fingerprint of a proposal's condition changes."""
    canonical = sorted((c.key.strip().lower(), _norm(c.value)) for c in changes)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()


def classify_rationale(rationale: str) -> tuple[str, list[str]]:
    """Map a free-text rationale to ``(category, resource constraints)`` by keyword table.

    Categories: ``resource`` (names an unavailable resource), ``already_done``,
    ``scientific`` (researcher judges it unnecessary/invalid), ``priority`` or ``other``.
    """
    text = rationale.lower()
    constraints = sorted(
        r for r, words in RESOURCE_KEYWORDS.items() if any(w.lower() in text for w in words)
    )
    for category, words in REASON_KEYWORDS.items():
        if any(w.lower() in text for w in words):
            return category, constraints
    return ("resource" if constraints else "other"), constraints


@dataclass
class PriorDecision:
    """A recorded decision joined with the proposal it decided."""

    decision_id: int
    proposal_id: int
    action: str
    rationale: str
    modifications: list[ProposalChange]
    experiment_id: int
    title: str
    signature: str
    template_id: str | None
    addresses_controls: list[str]
    reason_category: str
    constraints: list[str]
    evidence: Evidence | None = None

    @property
    def rejected(self) -> bool:
        return self.action == "reject"


@dataclass
class DecisionMemory:
    """All decisions of a project, indexed for the engines."""

    decisions: list[PriorDecision] = field(default_factory=list)

    @property
    def decided_signatures(self) -> set[str]:
        sigs = {d.signature for d in self.decisions}
        sigs |= {proposal_signature(d.modifications) for d in self.decisions if d.modifications}
        return sigs

    @property
    def unavailable_resources(self) -> set[str]:
        return {r for d in self.decisions if d.rejected for r in d.constraints}

    def for_control(self, control_id: str) -> list[PriorDecision]:
        return [d for d in self.decisions if control_id in d.addresses_controls]

    def for_template(self, template_id: str) -> list[PriorDecision]:
        return [d for d in self.decisions if d.template_id == template_id]

    def dismissed_controls(self) -> set[str]:
        """Controls a researcher rejected as scientifically unnecessary or already done."""
        return {
            c
            for d in self.decisions
            if d.rejected and d.reason_category in ("scientific", "already_done")
            for c in d.addresses_controls
        }

    def deferred_templates(self) -> set[str]:
        return {
            d.template_id
            for d in self.decisions
            if d.rejected and d.reason_category == "priority" and d.template_id
        }


def load_decisions(session: Session, project_id: int) -> DecisionMemory:
    """Decisions of a project, oldest first (Partner's own tables only)."""
    rows = session.execute(
        select(Decision, Proposal)
        .join(Proposal, Proposal.id == Decision.proposal_id)
        .where(Proposal.project_id == project_id)
        .order_by(Decision.id)
    ).all()
    out: list[PriorDecision] = []
    for decision, proposal in rows:
        changes = [ProposalChange.model_validate(c) for c in proposal.changes]
        design = proposal.design or {}
        category, constraints = classify_rationale(decision.rationale)
        out.append(
            PriorDecision(
                decision_id=decision.id,
                proposal_id=proposal.id,
                action=decision.action,
                rationale=decision.rationale,
                modifications=[ProposalChange.model_validate(m) for m in decision.modifications],
                experiment_id=proposal.experiment_id,
                title=proposal.title,
                signature=proposal.signature or proposal_signature(changes),
                template_id=design.get("template_id"),
                addresses_controls=list(design.get("addresses_controls", [])),
                reason_category=category,
                constraints=constraints,
            )
        )
    return DecisionMemory(out)


ACTION_LABEL: dict[str, str] = {"accept": "수락", "modify": "수정", "reject": "기각"}
