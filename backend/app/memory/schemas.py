"""Pydantic schemas for the Memory layer (API contract + cross-module DTOs).

Besides the API DTOs this module defines the **fact port** (:class:`FactProvider`)
through which higher layers (Analysis, Partner) feed stored results, QC flags and
partner records into Memory without Memory importing them (dependency inversion —
Memory may only depend on ELN). Providers are registered at the composition root
(``app/wiring.py``) via :func:`app.memory.service.register_fact_provider`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.eln.schemas import DatasetKind, ExperimentSummary

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

Engine = Literal["rules", "claude"]


# ------------------------------------------------------------- provenance


class SourceRef(BaseModel):
    """Pointer to the stored record (and field) a fact was read from."""

    ref_type: str = Field(description="<module>.<Entity>, e.g. 'eln.Experiment'")
    ref_id: int
    field: str = Field(description="Field path inside the record, e.g. 'condition_block.ph'")
    experiment_id: int | None = None


# ------------------------------------------------------------------- diff


class ConditionChange(BaseModel):
    key: str
    label: str
    change: Literal["added", "removed", "changed"]
    value_a: Any = None
    value_b: Any = None
    sources: list[SourceRef] = []


class NoteDiffSegment(BaseModel):
    """Word-level piece of a changed line (MEM-4)."""

    op: Literal["equal", "insert", "delete"]
    text: str


class NoteDiffLine(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str
    segments: list[NoteDiffSegment] = []


class DatasetDiff(BaseModel):
    only_a: list[DatasetKind]
    only_b: list[DatasetKind]
    both: list[DatasetKind]


class ResultDelta(BaseModel):
    """One stored result metric of both experiments. Values/deltas come from Analysis."""

    metric: str
    label: str
    analyte: str | None = None
    unit: str | None = None
    value_a: float | None = None
    value_b: float | None = None
    delta: float | None = Field(
        default=None, description="b − a as computed by the Analysis layer (None if not given)"
    )
    p_value: float | None = None
    sources: list[SourceRef] = []


class QCChange(BaseModel):
    """A QC flag present in one or both experiments (set comparison, no arithmetic)."""

    code: str
    analyte: str | None = None
    context: dict[str, Any] = {}
    change: Literal["appeared", "resolved", "persisting"]
    severity: str
    value_a: float | None = None
    value_b: float | None = None
    sources: list[SourceRef] = []


class ExperimentDiff(BaseModel):
    """Deterministic diff of two experiments: conditions, results, QC, note, datasets.

    Every item carries ``sources`` (experiment id + field) so it can be traced back.
    Result values and deltas are read from Analysis via the fact port; Memory itself
    only compares keys and sets.
    """

    a: ExperimentSummary
    b: ExperimentSummary
    relation: Literal["same", "a_is_ancestor", "b_is_ancestor", "siblings", "unrelated"]
    common_ancestor_id: int | None
    condition_changes: list[ConditionChange]
    unchanged_keys: list[str]
    note_diff: list[NoteDiffLine]
    datasets: DatasetDiff
    results_available: bool = False
    result_changes: list[ResultDelta] = []
    qc_changes: list[QCChange] = Field(
        default=[],
        description="Changes of warning/critical QC flags (``severity != 'info'``).",
    )
    qc_info_changes: list[QCChange] = Field(
        default=[],
        description=(
            "Changes of informational flags (``severity == 'info'``, e.g. "
            "``loq_above_lowest_level``, ``uncertainty_high``, ``outlier_suspected``), kept "
            "apart so they never count as QC failures appearing or being resolved."
        ),
    )


# --------------------------------------------------------------- timeline


class TimelineEntry(BaseModel):
    experiment_id: int
    code: str
    title: str
    performed_on: date
    parent_experiment_id: int | None
    changed_keys_vs_parent: list[str]
    dataset_kinds: list[DatasetKind]


class ConditionHistoryEntry(BaseModel):
    """Value of one condition key in one experiment (MEM-2)."""

    experiment_id: int
    code: str
    performed_on: date
    value: Any
    changed_from_previous: bool
    previous_value: Any = None
    source: SourceRef


class ConditionMatrixRow(BaseModel):
    key: str
    label: str
    values: list[Any] = Field(description="Aligned with ConditionMatrix.experiments")
    varying: bool


class ConditionMatrix(BaseModel):
    """Key × experiment matrix of condition values (MEM-5)."""

    experiments: list[ExperimentSummary]
    rows: list[ConditionMatrixRow]
    varying_only: bool


# ----------------------------------------------------------- lineage graph

GraphRelation = Literal["derived_from", "shares_conditions", "tests_proposal"]


class GraphNode(BaseModel):
    id: int
    code: str
    title: str
    performed_on: date
    depth: int


class GraphEdge(BaseModel):
    source: int
    target: int
    relation: GraphRelation
    changed_keys: list[str]
    similarity: float | None = None
    proposal_id: int | None = None


class ResearchGraph(BaseModel):
    project_id: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    roots: list[int]


# --------------------------------------------------------- knowledge graph

KGNodeType = Literal[
    "experiment",
    "condition",
    "analyte",
    "sample",
    "strain",
    "result",
    "critique",
    "hypothesis",
    "proposal",
    "decision",
    "note",
]
KGRelation = Literal[
    "derived_from",
    "uses_condition",
    "measures",
    "uses_sample",
    "uses_strain",
    "has_result",
    "flags",
    "critiqued_by",
    "raises_hypothesis",
    "proposes",
    "tests_hypothesis",
    "decided",
    "tests_proposal",
    "shares_conditions",
    "mentions",
]


class KGNode(BaseModel):
    id: str = Field(description="'<type>:<key>', e.g. 'experiment:7', 'analyte:carbendazim'")
    type: KGNodeType
    label: str
    ref_type: str | None = None
    ref_id: int | None = None
    experiment_id: int | None = None
    attrs: dict[str, Any] = {}


class KGEdge(BaseModel):
    source: str
    target: str
    relation: KGRelation
    source_ref: SourceRef | None = None
    attrs: dict[str, Any] = {}


class GraphRefresh(BaseModel):
    """How the cached graph was brought up to date for this response."""

    mode: Literal["full", "incremental", "cached"]
    applied_events: int
    last_event_id: int


class KnowledgeGraph(BaseModel):
    project_id: int
    nodes: list[KGNode]
    edges: list[KGEdge]
    counts: dict[str, int]
    refresh: GraphRefresh


# ------------------------------------------------------------------ search

SearchField = Literal[
    "title", "raw_note", "condition_block", "digest", "critique", "knowledge_note", "dataset"
]


class SearchIndexSync(BaseModel):
    """Result of synchronising the derived full-text index from the audit log."""

    indexed_events: int = Field(description="Audit events applied to the index by this call")
    project_ids: list[int] = Field(description="Projects whose index was synchronised")


class SearchHit(BaseModel):
    experiment_id: int
    code: str
    field: SearchField
    snippet: str
    score: float = 0.0
    highlights: list[tuple[int, int]] = Field(
        default=[], description="[start, end) character offsets of matches inside snippet"
    )
    source: SourceRef | None = None
    project_id: int | None = Field(
        default=None,
        description="Project of the experiment (set by project and cross-project search)",
    )


Facet = Literal["strain", "sample", "condition", "analyte", "keyword"]


class MatchedTerm(BaseModel):
    term: str
    facet: Facet
    matches: list[str] = Field(description="Vocabulary entries the term matched")


class RecallExperiment(BaseModel):
    experiment: ExperimentSummary
    score: float
    reasons: list[SearchHit]


class ProtocolGroup(BaseModel):
    """Experiments sharing an identical condition block (one protocol variant)."""

    protocol_id: str = Field(description="Short sha256 of the condition block")
    experiment_ids: list[int]
    codes: list[str]
    conditions: dict[str, Any]
    differs_from_first: list[str] = Field(
        description="Keys whose value differs from the first protocol in this bundle"
    )


class ResultFact(BaseModel):
    """A stored result value supplied by a higher layer (Analysis)."""

    metric: str
    label: str
    analyte: str | None = None
    value: float | None = None
    unit: str | None = None
    source: SourceRef


class RecallBundle(BaseModel):
    query: str
    terms: list[MatchedTerm]
    experiments: list[RecallExperiment]
    protocols: list[ProtocolGroup]
    results: list[ResultFact]
    project_ids: list[int] = Field(
        default=[],
        description="Projects searched (one for project recall, several for cross-project)",
    )


class EvidenceFragment(BaseModel):
    key: str = Field(description="Stable key cited by answers, e.g. 'F1'")
    experiment_id: int
    code: str
    text: str
    source: SourceRef


class MemoryAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=30)


class MemoryAnswerDraft(BaseModel):
    """Output schema shared by the rules and Claude answer engines."""

    answer: str
    fragment_keys: list[str]


class MemoryAnswer(BaseModel):
    question: str
    answer: str
    engine: Engine
    model: str | None = None
    fallback_reason: str | None = None
    fragment_keys: list[str]
    fragments: list[EvidenceFragment]


# ------------------------------------------------------------- similarity


class SimilarExperiment(BaseModel):
    experiment: ExperimentSummary
    score: float = Field(description="Condition-vector similarity in [0, 1]")
    shared_keys: list[str]
    differing: list[ConditionChange]


# ----------------------------------------------------------------- digests


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
    fallback_reason: str | None = None
    input_fingerprint: str | None = None
    stale: bool = False


# --------------------------------------------------------- knowledge notes


class KnowledgeNoteCreate(BaseModel):
    statement: str = Field(min_length=1, max_length=4000)
    linked_experiment_ids: list[int] = Field(min_length=1)
    author: str = ""


class KnowledgeNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    statement: str
    linked_experiment_ids: list[int]
    author: str
    created_at: datetime


class KnowledgeNoteList(BaseModel):
    project_id: int
    total: int
    items: list[KnowledgeNoteOut]


# ------------------------------------------------------------- fact port


class EntityFacts(BaseModel):
    """What a provider knows about one audited entity (labels, links, searchable text)."""

    ref_type: str
    ref_id: int
    label: str
    experiment_id: int | None = None
    critique_id: int | None = None
    hypothesis_id: int | None = None
    proposal_id: int | None = None
    status: str | None = None
    kind: str | None = None
    flagged_analytes: list[str] = []
    texts: dict[str, str] = {}


class ProposalFact(BaseModel):
    """A proposed next experiment: base experiment + condition changes.

    ``changes`` are the condition-block changes a follow-up would carry (Partner's
    ``implementing_changes``); ``decided_on`` is the decision day once decided.
    """

    id: int
    experiment_id: int
    created_at: datetime
    changes: dict[str, Any]
    status: str = "pending"
    decided_on: date | None = None


class QCFact(BaseModel):
    code: str
    severity: str
    analyte: str | None = None
    value: float | None = None
    context: dict[str, Any] = {}
    source: SourceRef


class FactProvider:
    """Port implemented by higher layers. Every method has a safe empty default.

    Implementations must only *read* stored records through their own module's
    service and must not compute new numbers for Memory.
    """

    name: str = "provider"

    def results(self, session: Session, experiment_id: int) -> list[ResultFact]:
        """Stored headline results of one experiment."""
        return []

    def results_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[ResultFact]]:
        """:meth:`results` of many experiments (every id a key). Override to batch reads."""
        return {i: self.results(session, i) for i in experiment_ids}

    def facts_many(
        self, session: Session, experiment_ids: list[int]
    ) -> tuple[dict[int, list[ResultFact]], dict[int, list[QCFact] | None]]:
        """:meth:`results_many` and :meth:`qc_flags_many` together (override to read once)."""
        return (
            self.results_many(session, experiment_ids),
            self.qc_flags_many(session, experiment_ids),
        )

    def result_deltas(self, session: Session, a_id: int, b_id: int) -> list[ResultDelta] | None:
        """Result comparison of two experiments, or ``None`` if not this provider's job."""
        return None

    def qc_flags(self, session: Session, experiment_id: int) -> list[QCFact] | None:
        """QC flags of the latest stored results, or ``None`` if not supported."""
        return None

    def qc_flags_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[QCFact] | None]:
        """:meth:`qc_flags` of many experiments (every id a key). Override to batch reads."""
        return {i: self.qc_flags(session, i) for i in experiment_ids}

    def describe(
        self,
        session: Session,
        ref_type: str,
        ref_id: int,
        project_id: int,
        payload: dict[str, Any],
    ) -> EntityFacts | None:
        """Labels/links for an audited entity this provider owns, else ``None``."""
        return None

    def describe_many(
        self,
        session: Session,
        ref_type: str,
        items: list[tuple[int, dict[str, Any]]],
        project_id: int,
    ) -> list[EntityFacts | None]:
        """:meth:`describe` of many ``(ref_id, payload)`` items of one type, in order.

        Override to batch reads; the default asks :meth:`describe` per item.
        """
        return [self.describe(session, ref_type, i, project_id, p) for i, p in items]

    def proposals(self, session: Session, project_id: int) -> list[ProposalFact]:
        """Stored proposals of a project (for ``tests_proposal`` edges)."""
        return []


# ------------------------------------------------------- failure archive

FailureTypeId = str
PatternLinkKind = Literal["retry", "same_condition"]


class FailureRecord(BaseModel):
    """One experiment whose stored QC has a critical flag (a failure), with its trigger.

    The trigger is what changed versus the parent experiment's condition block; the
    failure type is derived from it deterministically (see ``memory.failures``).
    """

    experiment: ExperimentSummary
    project_name: str
    parent: ExperimentSummary | None = None
    parent_failed: bool = False
    type_id: FailureTypeId = Field(
        description="initial | no_change | multi_change | change:<condition key>"
    )
    type_label: str
    failed_checks: list[str] = Field(description="Critical QC flag codes")
    failed_analytes: list[str]
    changes: list[ConditionChange] = Field(description="Condition changes versus the parent")
    recovery: ResultFact | None = Field(default=None, description="Stored mean recovery (copied)")
    sources: list[SourceRef] = Field(default=[], description="Stored QC flags of the failure")


class FailureType(BaseModel):
    id: FailureTypeId
    label: str
    count: int
    experiment_ids: list[int]


class FailurePatternLink(BaseModel):
    """Why two failures belong to one pattern."""

    kind: PatternLinkKind = Field(
        description="retry: child of a failed experiment failed again; same_condition: a later "
        "failure kept the condition value introduced by an earlier one and missed the same analyte"
    )
    from_experiment_id: int
    to_experiment_id: int
    key: str | None = None
    label: str | None = None
    value: Any = None
    shared_analytes: list[str] = []


class FailurePattern(BaseModel):
    """Two or more connected failures — the same failure repeated."""

    id: str
    experiment_ids: list[int] = Field(description="Chronological")
    codes: list[str]
    project_ids: list[int]
    shared_analytes: list[str] = Field(description="Analytes that failed in at least two members")
    links: list[FailurePatternLink]
    resolution: ExperimentSummary | None = Field(
        default=None,
        description="First later child of a member with a stored recovery and no critical flag",
    )
    resolution_qc: str | None = Field(default=None, description="pass | warning")
    resolution_changes: list[ConditionChange] = []
    resolution_recovery: ResultFact | None = None


class FailureArchive(BaseModel):
    project_ids: list[int]
    experiment_count: int
    analyzed_count: int = Field(description="Experiments with at least one stored result")
    failure_count: int
    types: list[FailureType]
    patterns: list[FailurePattern]
    failures: list[FailureRecord] = Field(description="Newest first")
