"""Pydantic schemas for the Memory layer."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.eln.schemas import DatasetKind, ExperimentSummary

Engine = Literal["rules", "claude"]


class ConditionChange(BaseModel):
    key: str
    label: str
    change: Literal["added", "removed", "changed"]
    value_a: Any = None
    value_b: Any = None


class NoteDiffLine(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class DatasetDiff(BaseModel):
    only_a: list[DatasetKind]
    only_b: list[DatasetKind]
    both: list[DatasetKind]


class ExperimentDiff(BaseModel):
    """Structural diff of two experiments' original records (no numbers computed here)."""

    a: ExperimentSummary
    b: ExperimentSummary
    relation: Literal["same", "a_is_ancestor", "b_is_ancestor", "siblings", "unrelated"]
    common_ancestor_id: int | None
    condition_changes: list[ConditionChange]
    unchanged_keys: list[str]
    note_diff: list[NoteDiffLine]
    datasets: DatasetDiff


class TimelineEntry(BaseModel):
    experiment_id: int
    code: str
    title: str
    performed_on: date
    parent_experiment_id: int | None
    changed_keys_vs_parent: list[str]
    dataset_kinds: list[DatasetKind]


class GraphNode(BaseModel):
    id: int
    code: str
    title: str
    performed_on: date
    depth: int


class GraphEdge(BaseModel):
    source: int
    target: int
    relation: Literal["derived_from"]
    changed_keys: list[str]


class ResearchGraph(BaseModel):
    project_id: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    roots: list[int]


class SearchHit(BaseModel):
    experiment_id: int
    code: str
    field: Literal["title", "raw_note", "condition_block", "digest"]
    snippet: str


class DigestDraft(BaseModel):
    """Output schema shared by rules and Claude digest engines."""

    summary: str = Field(description="2–3 sentence summary in Korean")
    key_points: list[str] = Field(description="Bullet observations quoted from the note")


class DigestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    engine: Engine
    model: str | None
    summary: str
    key_points: list[str]
    created_at: datetime
