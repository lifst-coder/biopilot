"""Pydantic schemas for the Partner layer.

``CritiqueDraft`` is the single output schema shared by the rules engine and the
Claude engine (CLAUDE.md §2: both modes use the same schema). The same holds for
``AskDraft`` (Q&A). Every field added here is *additive*: existing response fields
keep their names and meaning (CLAUDE.md §3, shared contracts).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.eln.schemas import ExperimentCreate

Engine = Literal["rules", "claude"]
Origin = Literal["user", "ai:rules", "ai:claude"]
Severity = Literal["info", "warning", "critical"]
EvidenceSource = Literal["eln", "memory", "analysis", "partner"]
CritiqueScope = Literal["experiment", "project"]
HypothesisStatus = Literal["proposed", "open", "supported", "refuted"]
ProposalStatus = Literal["pending", "accepted", "modified", "rejected"]


class Evidence(BaseModel):
    """A fact taken from a stored record. Numbers on screen come from ``value`` only."""

    key: str = Field(description="Stable key cited by findings, e.g. 'E3'")
    source: EvidenceSource
    ref_type: str = Field(description="<module>.<Entity> of the source record")
    ref_id: int
    label: str
    value: float | None = None
    unit: str | None = None
    text: str | None = None


class Finding(BaseModel):
    title: str
    body: str
    severity: Severity
    evidence_keys: list[str]


class HypothesisDraft(BaseModel):
    statement: str
    rationale: str
    evidence_keys: list[str]


class ProposalChange(BaseModel):
    """A change to a condition-block key for a proposed next experiment."""

    key: str
    value: str | float | None


# ------------------------------------------------------------ Research Critic

ArgumentBasis = Literal["data", "domain_rule", "decision"]


class CriticArgument(BaseModel):
    """One argument in a structured critique.

    ``basis`` says what the argument rests on: ``data`` (stored evidence),
    ``domain_rule`` (documented domain knowledge, not measured here) or ``decision``
    (a recorded researcher decision).
    """

    statement: str
    evidence_keys: list[str] = []
    basis: ArgumentBasis = "data"


class AlternativeExplanation(BaseModel):
    """A competing explanation of the observation with its own pro/contra arguments."""

    id: str = Field(description="Stable id, e.g. 'matrix_suppression'")
    label: str
    mechanism: str
    supporting: list[CriticArgument] = []
    opposing: list[CriticArgument] = []
    status: Literal["plausible", "weakened", "untested"] = "untested"


class MissingControl(BaseModel):
    """A control/measurement that is absent but needed to separate explanations."""

    id: str = Field(description="Stable id, e.g. 'pre_post_spike'")
    name: str
    purpose: str
    distinguishes: list[str] = Field(
        default=[], description="AlternativeExplanation ids this control separates"
    )
    evidence_keys: list[str] = []
    decision_note: str | None = Field(
        default=None, description="How a recorded decision on this control was taken into account"
    )


Verdict = Literal["supported", "refuted", "indeterminate", "no_issue"]


class CriticAssessment(BaseModel):
    """Structured Research Critic output for one claim.

    Sections map 1:1 to the critic contract: 지지 근거 / 반대 근거 / 누락 대조군 /
    대안 설명 / 현재 데이터로 확정 불가한 이유.
    """

    id: str = Field(description="Stable id, e.g. 'recovery_cause'")
    question: str
    claim: str
    verdict: Verdict
    verdict_reason: str
    supporting_evidence: list[CriticArgument] = []
    opposing_evidence: list[CriticArgument] = []
    missing_controls: list[MissingControl] = []
    alternative_explanations: list[AlternativeExplanation] = []
    undetermined_reasons: list[CriticArgument] = []


# ------------------------------------------------- Next Experiment Designer

DiscriminatingPower = Literal["high", "medium", "low"]


class DesignVariable(BaseModel):
    """A variable of the proposed experiment (varied or held fixed)."""

    key: str
    label: str
    role: Literal["varied", "fixed"]
    levels: list[str | float | None] = []


class DesignControl(BaseModel):
    name: str
    purpose: str


class ExpectedOutcome(BaseModel):
    """If-then reading of the result: what each outcome would imply."""

    observation: str
    interpretation: str
    supports: list[str] = Field(default=[], description="AlternativeExplanation ids")


class ExperimentDesign(BaseModel):
    """Next-experiment design: variables, controls, replicates, measurements, power."""

    template_id: str | None = Field(default=None, description="Rules design template id")
    objective: str
    variables: list[DesignVariable] = []
    controls: list[DesignControl] = []
    replicates: int | None = Field(
        default=None, description="Replicates per level — taken from stored data, never invented"
    )
    replicates_basis: str | None = None
    replicates_evidence_key: str | None = None
    measurements: list[str] = []
    expected_outcomes: list[ExpectedOutcome] = []
    discriminating_power: DiscriminatingPower = "medium"
    discriminates: list[str] = Field(default=[], description="AlternativeExplanation ids")
    power_rationale: str = ""
    addresses_controls: list[str] = Field(default=[], description="MissingControl ids")
    basis_experiment_ids: list[int] = Field(
        default=[], description="Experiments whose stored records justify this design"
    )
    requires: list[str] = Field(
        default=[], description="Resources needed, e.g. 'blank_matrix' (matched to rejections)"
    )


class ProposalDraft(BaseModel):
    title: str
    description: str
    changes: list[ProposalChange]
    evidence_keys: list[str]
    hypothesis_index: int | None = Field(
        default=None, description="Index into CritiqueDraft.hypotheses this proposal tests"
    )
    design: ExperimentDesign | None = None
    base_experiment_id: int | None = Field(
        default=None, description="Experiment whose conditions the changes apply to"
    )
    supersedes_proposal_ids: list[int] = Field(
        default=[], description="Decided proposals this one replaces (e.g. after a rejection)"
    )


FeedbackApplied = Literal["suppressed_repeat", "alternative_proposed", "noted", "awaiting_result"]


class DecisionFeedback(BaseModel):
    """How a recorded researcher decision was reflected in a critique."""

    decision_id: int
    proposal_id: int
    action: Literal["accept", "modify", "reject"]
    rationale: str
    reason_category: str
    applied: FeedbackApplied
    note: str
    evidence_key: str | None = None


class CritiqueDraft(BaseModel):
    """Engine output (rules or Claude) — validated and grounded before storage."""

    summary: str
    findings: list[Finding]
    hypotheses: list[HypothesisDraft]
    proposals: list[ProposalDraft]
    assessments: list[CriticAssessment] = []
    decision_feedback: list[DecisionFeedback] = []


class CritiqueOut(BaseModel):
    id: int
    project_id: int
    scope: CritiqueScope
    experiment_id: int | None
    baseline_experiment_id: int | None
    engine: Engine
    model: str | None
    fallback_reason: str | None
    summary: str
    findings: list[Finding]
    assessments: list[CriticAssessment]
    decision_feedback: list[DecisionFeedback]
    evidence: list[Evidence]
    hypothesis_ids: list[int]
    proposal_ids: list[int]
    context_fingerprint: str | None
    created_at: datetime


# -------------------------------------------------------------- hypotheses


class HypothesisCreate(BaseModel):
    project_id: int
    experiment_id: int | None = None
    statement: str = Field(min_length=1)
    rationale: str = ""


class HypothesisStatusChange(BaseModel):
    """Request to move a hypothesis along proposed → open → supported/refuted."""

    status: HypothesisStatus
    rationale: str = Field(min_length=1, description="Why — required for every transition")
    evidence_result_ids: list[int] = Field(
        default=[], description="AnalysisResult ids backing the transition"
    )
    decided_by: str = "researcher"


class HypothesisTransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hypothesis_id: int
    from_status: HypothesisStatus
    to_status: HypothesisStatus
    rationale: str
    evidence_result_ids: list[int]
    decided_by: str
    created_at: datetime


class HypothesisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    experiment_id: int | None
    critique_id: int | None
    statement: str
    rationale: str
    status: HypothesisStatus
    origin: Origin
    evidence_keys: list[str]
    transitions: list[HypothesisTransitionOut] = []
    created_at: datetime


# --------------------------------------------------------------- decisions

DecisionAction = Literal["accept", "modify", "reject"]


class DecisionCreate(BaseModel):
    action: DecisionAction
    rationale: str = Field(min_length=1, description="Why — required for every decision")
    modifications: list[ProposalChange] = []
    decided_by: str = "researcher"

    @model_validator(mode="after")
    def _modify_needs_changes(self) -> DecisionCreate:
        if self.action == "modify" and not self.modifications:
            raise ValueError("modify decisions must include modifications")
        if self.action != "modify" and self.modifications:
            raise ValueError("only modify decisions may include modifications")
        return self


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposal_id: int
    action: DecisionAction
    rationale: str
    modifications: list[ProposalChange]
    decided_by: str
    reason_category: str = "other"
    constraints: list[str] = []
    created_at: datetime


class PriorityFactor(BaseModel):
    """One additive term of a proposal's deterministic priority score."""

    name: str
    points: int
    detail: str
    evidence_keys: list[str] = []


class ProposalOut(BaseModel):
    id: int
    project_id: int
    experiment_id: int
    critique_id: int | None
    hypothesis_id: int | None
    title: str
    description: str
    changes: list[ProposalChange]
    evidence_keys: list[str]
    status: ProposalStatus
    origin: Origin
    decision: DecisionOut | None
    design: ExperimentDesign | None = None
    base_experiment_id: int | None = None
    priority: int = 0
    priority_factors: list[PriorityFactor] = []
    signature: str | None = None
    supersedes_proposal_ids: list[int] = []
    created_at: datetime


class DecisionHistoryEntry(BaseModel):
    """A decision with the proposal it decided and where it was fed back."""

    decision: DecisionOut
    proposal_id: int
    proposal_title: str
    proposal_changes: list[ProposalChange]
    experiment_id: int
    experiment_code: str
    reflected_in_critique_ids: list[int] = Field(
        default=[], description="Later critiques whose decision_feedback cites this decision"
    )


class DecisionHistory(BaseModel):
    project_id: int
    entries: list[DecisionHistoryEntry]


class ExperimentDraftOut(BaseModel):
    """Unsaved ``ExperimentCreate`` built from a proposal (creation happens in ELN)."""

    proposal_id: int
    proposal_status: ProposalStatus
    ready: bool = Field(description="True when the proposal was accepted or modified")
    base_experiment_id: int
    base_experiment_code: str
    applied_changes: list[ProposalChange]
    notes: list[str]
    draft: ExperimentCreate


# ---------------------------------------------------------------------- mode


class PartnerMode(BaseModel):
    mode: Engine
    model: str | None
    description: str


# ----------------------------------------------------------------------- ask

StatementKind = Literal["fact", "inference", "estimate"]


class AnswerStatement(BaseModel):
    """One sentence of an answer.

    ``fact`` restates stored evidence, ``inference`` is a rule-based judgement over
    cited evidence, ``estimate`` (추정) has no direct supporting data. Statements
    without evidence keys are always downgraded to ``estimate``.
    """

    text: str
    kind: StatementKind
    evidence_keys: list[str] = []


class SourceRef(BaseModel):
    """A stored record an answer relies on (for 출처 display)."""

    ref_type: str
    ref_id: int
    label: str


class AskRequest(BaseModel):
    project_id: int
    experiment_id: int | None = None
    question: str = Field(min_length=1, max_length=2000)


class AskDraft(BaseModel):
    """Q&A output schema shared by the rules and Claude engines."""

    answer: str
    evidence_keys: list[str] = Field(default_factory=list)
    statements: list[AnswerStatement] = Field(default_factory=list)


AskIntent = Literal["cause", "next_experiment", "decisions", "facts", "project"]


class AskResponse(BaseModel):
    answer: str
    engine: Engine
    evidence: list[Evidence]
    topics: list[str]
    intent: AskIntent = "facts"
    experiment_id: int | None = None
    statements: list[AnswerStatement] = []
    sources: list[SourceRef] = []
    critique_id: int | None = None
    proposal_ids: list[int] = []
    exchange_id: int | None = None
    fallback_reason: str | None = None


class ExchangeOut(BaseModel):
    """A stored question/answer pair (immutable)."""

    id: int
    project_id: int
    experiment_id: int | None
    question: str
    response: AskResponse
    created_at: datetime


class ExchangeHistory(BaseModel):
    project_id: int
    experiment_id: int | None
    items: list[ExchangeOut]
