"""Pydantic schemas for the Partner layer.

``CritiqueDraft`` is the single output schema shared by the rules engine and the
Claude engine (CLAUDE.md §2: both modes use the same schema).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Engine = Literal["rules", "claude"]
Origin = Literal["user", "ai:rules", "ai:claude"]
Severity = Literal["info", "warning", "critical"]


class Evidence(BaseModel):
    """A fact taken from a stored record. Numbers on screen come from ``value`` only."""

    key: str = Field(description="Stable key cited by findings, e.g. 'E3'")
    source: Literal["eln", "memory", "analysis"]
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


class ProposalDraft(BaseModel):
    title: str
    description: str
    changes: list[ProposalChange]
    evidence_keys: list[str]
    hypothesis_index: int | None = Field(
        default=None, description="Index into CritiqueDraft.hypotheses this proposal tests"
    )


class CritiqueDraft(BaseModel):
    """Engine output (rules or Claude) — validated and grounded before storage."""

    summary: str
    findings: list[Finding]
    hypotheses: list[HypothesisDraft]
    proposals: list[ProposalDraft]


class CritiqueOut(BaseModel):
    id: int
    experiment_id: int
    baseline_experiment_id: int | None
    engine: Engine
    model: str | None
    fallback_reason: str | None
    summary: str
    findings: list[Finding]
    evidence: list[Evidence]
    hypothesis_ids: list[int]
    proposal_ids: list[int]
    created_at: datetime


class HypothesisCreate(BaseModel):
    project_id: int
    experiment_id: int | None = None
    statement: str = Field(min_length=1)
    rationale: str = ""


class HypothesisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    experiment_id: int | None
    critique_id: int | None
    statement: str
    rationale: str
    status: Literal["proposed", "open", "supported", "refuted"]
    origin: Origin
    evidence_keys: list[str]
    created_at: datetime


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
    created_at: datetime


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
    status: Literal["pending", "accepted", "modified", "rejected"]
    origin: Origin
    decision: DecisionOut | None
    created_at: datetime


class PartnerMode(BaseModel):
    mode: Engine
    model: str | None
    description: str


class AskRequest(BaseModel):
    project_id: int
    experiment_id: int | None = None
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    answer: str
    engine: Engine
    evidence: list[Evidence]
    topics: list[str]
