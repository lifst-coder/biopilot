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
import re
import unicodedata
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
    """Order-independent fingerprint of a proposal's condition changes.

    Stored on every proposal and referenced by the seed decision history, so its
    canonical form must not change. Looser comparisons use :func:`proposal_intent`.
    """
    canonical = sorted((c.key.strip().lower(), _norm(c.value)) for c in changes)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()


_NUMBER_WITH_UNIT = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*([a-zµ%]+)?$")


def _loose(value: object) -> str:
    """Value normalised for paraphrase-resistant comparison (ISSUES P1-8).

    NFKC, lower case, unicode minus/×/superscripts folded, whitespace removed;
    a lone number with an optional unit word keeps only the number (``"5 min"`` ≡ ``5``
    ≡ ``5.0``), so a restated value is still recognised as the same change.
    """
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    text = text.replace("−", "-").replace("×", "x")
    match = _NUMBER_WITH_UNIT.match(text)
    if match:
        return f"{float(match.group(1)):g}"
    return re.sub(r"\s+", "", text)


def proposal_intent(changes: list[ProposalChange]) -> str:
    """Looser, order-independent key of a change set (keys and values normalised).

    Used only to detect a decided proposal restated with different spelling (Claude
    mode); the stored :func:`proposal_signature` stays the exact fingerprint.
    """
    canonical = sorted(
        (re.sub(r"[\s-]+", "_", c.key.strip().lower()), _loose(c.value)) for c in changes
    )
    return json.dumps(canonical, ensure_ascii=False)


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
    changes: list[ProposalChange] = field(default_factory=list)

    @property
    def rejected(self) -> bool:
        return self.action == "reject"


@dataclass
class DecisionMemory:
    """All decisions of a project, indexed for the engines."""

    decisions: list[PriorDecision] = field(default_factory=list)

    @property
    def decided_signatures(self) -> set[str]:
        """Exact fingerprints of every decided proposal and of every modification."""
        sigs = {d.signature for d in self.decisions}
        sigs |= {proposal_signature(d.modifications) for d in self.decisions if d.modifications}
        return sigs

    @property
    def decided_intents(self) -> set[str]:
        """Normalised change sets (:func:`proposal_intent`) of decided proposals."""
        intents = {proposal_intent(d.changes) for d in self.decisions if d.changes}
        intents |= {proposal_intent(d.modifications) for d in self.decisions if d.modifications}
        return intents

    def repeated_by(
        self, changes: list[ProposalChange], experiment_id: int | None
    ) -> list[PriorDecision]:
        """Decisions that a proposal with ``changes`` would repeat.

        Matches the exact signature or a restatement (:func:`proposal_intent`) of the
        proposal or of its modifications. Rejections count project-wide; acceptances and
        modifications only on the experiment they were decided for (``None`` = any).
        """
        sig, intent = proposal_signature(changes), proposal_intent(changes)
        out: list[PriorDecision] = []
        for d in self.decisions:
            if not d.rejected and experiment_id is not None and d.experiment_id != experiment_id:
                continue
            sigs = {d.signature} | (
                {proposal_signature(d.modifications)} if d.modifications else set()
            )
            intents = {proposal_intent(c) for c in (d.changes, d.modifications) if c}
            if sig in sigs or intent in intents:
                out.append(d)
        return out

    @property
    def unavailable_resources(self) -> set[str]:
        """Resources named in rejection rationales (lab-wide facts, project-wide scope)."""
        return {r for d in self.decisions if d.rejected for r in d.constraints}

    def for_control(self, control_id: str) -> list[PriorDecision]:
        """Decisions on proposals that addressed ``control_id``."""
        return [d for d in self.decisions if control_id in d.addresses_controls]

    def for_template(self, template_id: str) -> list[PriorDecision]:
        """Decisions on proposals instantiated from ``template_id``."""
        return [d for d in self.decisions if d.template_id == template_id]

    def dismissed_controls(self, experiment_id: int) -> set[str]:
        """Controls rejected as scientifically unnecessary or already done *for this experiment*.

        The judgement is about one experiment's data (ISSUES P1-8): it no longer silences
        the control for every later experiment of the project.
        """
        return {
            c
            for d in self.decisions
            if d.rejected
            and d.experiment_id == experiment_id
            and d.reason_category in ("scientific", "already_done")
            for c in d.addresses_controls
        }

    def deferred_templates(self, experiment_id: int) -> set[str]:
        """Templates postponed ("나중에", "보류") for this experiment."""
        return {
            d.template_id
            for d in self.decisions
            if d.rejected
            and d.experiment_id == experiment_id
            and d.reason_category == "priority"
            and d.template_id
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
                changes=changes,
            )
        )
    return DecisionMemory(out)


ACTION_LABEL: dict[str, str] = {"accept": "수락", "modify": "수정", "reject": "기각"}
