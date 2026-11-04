"""Pydantic schemas (API contract + cross-module DTOs) for the ELN layer.

Other modules may import anything defined (or re-exported) here. Field *additions* are
free; removals/renames go through CHANGES_REQUESTED.md (CLAUDE.md §3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DatasetKind = Literal["calibration", "recovery", "matrix_effect", "ion_ratio", "other"]
IssueLevel = Literal["error", "warning"]
HistoryKind = Literal["created", "metadata", "addendum", "dataset", "attachment"]

# ------------------------------------------------------- dataset kind registry


#: Longest stored file name (``String(255)`` name columns of datasets/attachments).
MAX_FILENAME_LENGTH = 255
#: Largest CSV accepted, as uploaded bytes or as JSON ``content`` characters.
MAX_CSV_BYTES = 5 * 1024 * 1024


class DatasetKindSpec(BaseModel):
    """One version of a dataset kind's CSV contract (``kind@version``)."""

    kind: DatasetKind
    version: int = Field(ge=1)
    description: str
    required_columns: list[str]
    numeric_columns: list[str] = []
    optional_columns: list[str] = []
    #: Columns restricted to a fixed vocabulary (e.g. ``curve`` ∈ {solvent, matrix}).
    enum_columns: dict[str, list[str]] = {}
    #: Columns whose values must be unique per row (duplicates are warnings).
    unique_columns: list[str] = []
    deprecated: bool = False

    @property
    def ref(self) -> str:
        """``kind@version`` identifier stored with every dataset."""
        return f"{self.kind}@{self.version}"


def _spec(kind: DatasetKind, version: int, description: str, **kw: Any) -> DatasetKindSpec:
    return DatasetKindSpec(kind=kind, version=version, description=description, **kw)


#: Versioned ingestion contracts. Append new versions; never edit a published one.
DATASET_KIND_REGISTRY: dict[str, list[DatasetKindSpec]] = {
    "calibration": [
        _spec(
            "calibration",
            1,
            "검량선 표준 주입 (수준별 분석물/내부표준 면적)",
            required_columns=["injection_id", "level_ng_ml", "analyte", "analyte_area", "is_area"],
            numeric_columns=["level_ng_ml", "analyte_area", "is_area"],
        )
    ],
    "recovery": [
        _spec(
            "recovery",
            1,
            "첨가 회수 시료 주입",
            required_columns=[
                "injection_id",
                "sample_id",
                "analyte",
                "spike_ng_g",
                "analyte_area",
                "is_area",
            ],
            numeric_columns=["spike_ng_g", "analyte_area", "is_area"],
        )
    ],
    "matrix_effect": [
        _spec(
            "matrix_effect",
            1,
            "용매/매트릭스 검량선 비교",
            required_columns=["injection_id", "curve", "level_ng_ml", "analyte", "analyte_area"],
            numeric_columns=["level_ng_ml", "analyte_area"],
            enum_columns={"curve": ["solvent", "matrix"]},
        )
    ],
    "ion_ratio": [
        _spec(
            "ion_ratio",
            1,
            "정성 이온비 (qualifier/quantifier 면적)",
            required_columns=[
                "injection_id",
                "sample_type",
                "analyte",
                "quantifier_area",
                "qualifier_area",
            ],
            numeric_columns=["quantifier_area", "qualifier_area"],
            optional_columns=["sample_id", "level_ng_ml"],
            enum_columns={"sample_type": ["standard", "sample"]},
        )
    ],
    "other": [_spec("other", 1, "기타 표 형식 데이터 (컬럼 제약 없음)", required_columns=[])],
}


def latest_kind_spec(kind: str) -> DatasetKindSpec:
    """Newest non-deprecated version of ``kind`` (``KeyError`` if unknown)."""
    versions = [s for s in DATASET_KIND_REGISTRY[kind] if not s.deprecated]
    return max(versions or DATASET_KIND_REGISTRY[kind], key=lambda s: s.version)


def kind_spec(kind: str, version: int | None = None) -> DatasetKindSpec:
    """Spec for ``kind@version`` (latest when ``version`` is ``None``)."""
    if version is None:
        return latest_kind_spec(kind)
    for spec in DATASET_KIND_REGISTRY[kind]:
        if spec.version == version:
            return spec
    raise KeyError(f"{kind}@{version}")


#: Required CSV columns per dataset kind (latest version). Backwards-compatible view of
#: :data:`DATASET_KIND_REGISTRY` that Analysis relies on.
DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    kind: tuple(latest_kind_spec(kind).required_columns) for kind in DATASET_KIND_REGISTRY
}

DATASET_NUMERIC_COLUMNS: frozenset[str] = frozenset(
    c for versions in DATASET_KIND_REGISTRY.values() for s in versions for c in s.numeric_columns
)

# ---------------------------------------------------------------- conditions


class ConditionBlock(BaseModel):
    """Structured experimental conditions. Unknown keys are preserved (``extra=allow``)."""

    model_config = ConfigDict(extra="allow")

    matrix: str | None = None
    sample_mass_g: float | None = None
    extraction_solvent: str | None = None
    extraction_volume_ml: float | None = None
    extraction_time_min: float | None = None
    ph: float | None = None
    buffer: str | None = None
    cleanup_sorbent: str | None = None
    column: str | None = None
    column_temp_c: float | None = None
    internal_standard: str | None = None
    calibration_weighting: Literal["none", "1/x", "1/x2"] | None = None
    instrument: str | None = None


class ConditionField(BaseModel):
    """Display + input metadata for a condition-block key."""

    key: str
    label: str
    unit: str | None = None
    value_type: Literal["number", "text", "choice"] = "text"
    options: list[str] = []
    description: str = ""


class ConditionRule(BaseModel):
    """Validation rule for one condition key inside a project template.

    ``min``/``max`` are hard limits (violations are errors → HTTP 400);
    ``warn_min``/``warn_max`` describe the usual range (violations are warnings).
    """

    key: str = Field(min_length=1, max_length=64)
    label: str | None = None
    unit: str | None = None
    required: bool = False
    required_level: IssueLevel = "warning"
    min: float | None = None
    max: float | None = None
    warn_min: float | None = None
    warn_max: float | None = None
    allowed: list[str] | None = None


class ConditionTemplateCreate(BaseModel):
    """New version of a project's condition template."""

    rules: list[ConditionRule] = Field(min_length=1)
    note: str = ""


class ConditionTemplateOut(BaseModel):
    """Effective template of a project (stored version or the built-in default)."""

    id: int | None
    project_id: int
    version: int
    source: Literal["project", "default"]
    rules: list[ConditionRule]
    note: str
    created_at: datetime | None


class ConditionIssue(BaseModel):
    """One template finding for a condition block."""

    key: str
    level: IssueLevel
    code: Literal["required_missing", "below_min", "above_max", "outside_usual", "not_allowed"]
    message: str


class ConditionCheck(BaseModel):
    """Result of validating a condition block against the project template."""

    ok: bool
    template_version: int
    template_source: Literal["project", "default"]
    issues: list[ConditionIssue]


class Attachment(BaseModel):
    """Metadata of a non-tabular attachment (chromatogram image, PDF, ...)."""

    name: str
    media_type: str
    description: str = ""


class AttachmentFileOut(BaseModel):
    """A stored attachment binary (content-addressed by sha256, immutable)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    name: str
    media_type: str
    description: str
    size_bytes: int
    sha256: str
    created_at: datetime
    download_url: str = ""


class ExperimentAddendumCreate(BaseModel):
    """Supplementary note appended to an experiment without touching the original."""

    note: str = Field(min_length=1)
    author: str = ""


class ExperimentAddendumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    note: str
    author: str
    created_at: datetime


# ---------------------------------------------------------------- projects


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = ""
    description: str = ""


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    objective: str
    description: str
    created_at: datetime
    experiment_count: int = 0


# ------------------------------------------------------------- experiments


class ExperimentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, examples=["#025"])
    title: str = Field(min_length=1, max_length=200)
    author: str = ""
    performed_on: date
    parent_experiment_id: int | None = None
    raw_note: str
    condition_block: ConditionBlock
    attachments: list[Attachment] = []
    #: Provenance: experiment this one was cloned from (form prefill), if any.
    cloned_from_experiment_id: int | None = None
    #: Provenance: protocol template used to prefill the form, if any.
    protocol_template_id: int | None = None


class ExperimentSummary(BaseModel):
    """List-view representation (no raw note body)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    code: str
    title: str
    author: str
    performed_on: date
    parent_experiment_id: int | None
    dataset_kinds: list[DatasetKind] = []


class ExperimentOut(ExperimentSummary):
    """Full experiment record including immutable originals."""

    raw_note: str
    condition_block: ConditionBlock
    attachments: list[Attachment]
    created_at: datetime
    cloned_from_experiment_id: int | None = None
    protocol_template_id: int | None = None
    revision: int = 1
    addenda: list[ExperimentAddendumOut] = []
    attachment_files: list[AttachmentFileOut] = []
    #: Template warnings raised when the experiment was created (create response only).
    warnings: list[ConditionIssue] = []


class ExperimentMetadataUpdate(BaseModel):
    """Correction of mutable metadata. Any other field in the body → 409."""

    model_config = ConfigDict(extra="allow")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=100)
    reason: str = ""


class ExperimentDraft(BaseModel):
    """Unsaved prefill for the experiment form (blank, clone or protocol template)."""

    source: Literal["blank", "clone", "template"]
    suggested_code: str
    draft: ExperimentCreate


# ------------------------------------------------------------ history/audit


class HistoryEntry(BaseModel):
    """One step in an experiment's version history."""

    kind: HistoryKind
    occurred_at: datetime
    #: Metadata revision in effect after this entry (1 = as created).
    revision: int
    summary: str
    ref_type: str
    ref_id: int
    title: str
    author: str
    changes: dict[str, dict[str, Any]] = {}


class ExperimentHistory(BaseModel):
    experiment_id: int
    current_revision: int
    entries: list[HistoryEntry]


# ---------------------------------------------------------------- datasets


class DatasetCreate(BaseModel):
    kind: DatasetKind
    filename: str = Field(min_length=1, max_length=MAX_FILENAME_LENGTH)
    content: str = Field(
        min_length=1,
        max_length=MAX_CSV_BYTES,
        description="Raw CSV text (UTF-8, header row first, at most 5 MiB characters)",
    )
    schema_version: int | None = Field(
        default=None, ge=1, description="Contract version (kind@version); latest when omitted"
    )
    supersedes_dataset_id: int | None = Field(
        default=None, description="Earlier dataset this upload replaces (re-upload)"
    )


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    kind: DatasetKind
    filename: str
    sha256: str
    row_count: int
    columns: list[str]
    created_at: datetime
    schema_version: int = 1
    schema_ref: str = ""
    source_encoding: str = "utf-8"
    supersedes_dataset_id: int | None = None
    superseded_by_dataset_id: int | None = None
    source_attachment_id: int | None = None


class DatasetPreview(BaseModel):
    dataset: DatasetOut
    rows: list[dict[str, Any]]
    truncated: bool


class CsvIssue(BaseModel):
    """One validation finding for a CSV upload. ``row`` is 1-based over data rows."""

    level: IssueLevel
    code: str
    message: str
    row: int | None = None
    column: str | None = None


class DatasetValidation(BaseModel):
    """Dry-run result of parsing + validating a CSV against ``kind@version``."""

    ok: bool
    kind: DatasetKind
    schema_ref: str
    filename: str
    encoding: str
    sha256: str | None
    row_count: int
    columns: list[str]
    preview_rows: list[dict[str, Any]]
    issues: list[CsvIssue]


class ImportFormat(BaseModel):
    """An instrument export layout the converter understands."""

    name: str
    label: str
    description: str
    target_kinds: list[DatasetKind]
    example_header: list[str]


class ImportPreview(BaseModel):
    """Vendor (wide) file converted to the long contract — not stored."""

    format: str
    kind: DatasetKind
    analytes: list[str]
    source_rows: int
    converted_csv: str
    validation: DatasetValidation


# ------------------------------------------------- protocol steps · extraction

#: Longest pasted protocol text accepted (characters).
MAX_PROTOCOL_TEXT = 20_000

ExtractionEngine = Literal["rules", "claude"]
#: ``recognized`` = one value found verbatim; ``unrecognized`` = nothing found (left
#: empty, never guessed); ``ambiguous`` = several different values or a range (left empty).
ExtractionStatus = Literal["recognized", "unrecognized", "ambiguous"]


class ProtocolStep(BaseModel):
    """One step of an executable protocol.

    ``condition_keys`` name condition-block keys whose planned values belong to this
    step; the values themselves live in the template's ``condition_block``.
    """

    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=2000)
    condition_keys: list[str] = Field(default=[], max_length=40)


class ProtocolExtractionRequest(BaseModel):
    """Pasted free text or table (TSV, Markdown table, ``key: value`` lines)."""

    text: str = Field(min_length=1, max_length=MAX_PROTOCOL_TEXT)


class ExtractedField(BaseModel):
    """Candidate value for one known condition key, with the line it was read from."""

    key: str
    label: str
    unit: str | None = None
    value_type: Literal["number", "text", "choice"] = "text"
    value: str | float | None = None
    status: ExtractionStatus
    #: The pasted line the value was read from (verbatim), for the researcher to check.
    source_text: str | None = None
    #: 1-based line number in the pasted text.
    line: int | None = None
    #: Different values found for this key (``ambiguous``), verbatim.
    candidates: list[str] = []
    note: str = ""


class ExtractedStep(BaseModel):
    """Candidate procedure step (numbered line or line of the procedure section)."""

    title: str
    detail: str = ""
    condition_keys: list[str] = []
    line: int | None = None


class UnmatchedLine(BaseModel):
    """A pasted line with numbers that no condition key could be read from."""

    line: int
    text: str


class ProtocolExtraction(BaseModel):
    """Extraction candidates — **not stored**; the researcher confirms them before saving.

    Both engines return this schema. ``fields`` lists every known condition key in a
    fixed order; keys that were not found are ``unrecognized`` with ``value=None``.
    """

    engine: ExtractionEngine
    model: str | None = None
    fallback_reason: str | None = None
    fields: list[ExtractedField]
    steps: list[ExtractedStep]
    unmatched_lines: list[UnmatchedLine]
    recognized_count: int
    field_count: int
    source_sha256: str


class ExtractionSnapshot(BaseModel):
    """The extraction the researcher reviewed, sent back with the confirmed protocol."""

    engine: ExtractionEngine
    model: str | None = None
    fallback_reason: str | None = None
    fields: list[ExtractedField] = Field(default=[], max_length=200)


class DraftField(BaseModel):
    """Claude output: one condition value and the verbatim line it was read from."""

    key: str
    value: str
    source_text: str


class DraftStep(BaseModel):
    """Claude output: one procedure step and the condition keys it uses."""

    title: str
    detail: str
    condition_keys: list[str]


class ProtocolExtractionDraft(BaseModel):
    """Structured output requested from Claude (validated against the pasted text)."""

    fields: list[DraftField]
    steps: list[DraftStep]


ReviewOutcome = Literal["accepted", "edited", "added", "cleared", "left_empty"]


class ExtractionReviewItem(BaseModel):
    """What the researcher did with one candidate (stored with the template)."""

    key: str
    label: str
    candidate: str | float | None = None
    candidate_status: ExtractionStatus
    source_text: str | None = None
    confirmed: Any = None
    outcome: ReviewOutcome


class ExtractionReview(BaseModel):
    """Stored provenance: engine, candidates and the researcher's confirmation."""

    engine: ExtractionEngine
    model: str | None = None
    fallback_reason: str | None = None
    items: list[ExtractionReviewItem]
    accepted_count: int
    edited_count: int
    added_count: int


# ------------------------------------------------------------ protocol templates


class ProtocolTemplateCreate(BaseModel):
    """Reusable protocol. Saving an existing name creates a new version.

    ``source_text`` (pasted original) and ``extraction`` (the reviewed candidates) are
    stored unchanged with the template as its original record.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    raw_note_template: str | None = None
    condition_block: ConditionBlock | None = None
    source_experiment_id: int | None = None
    author: str = ""
    #: Researcher-facing version name (``v1.1``); defaults to ``v<version>``.
    version_label: str = Field(default="", max_length=20)
    steps: list[ProtocolStep] | None = Field(default=None, max_length=60)
    source_text: str | None = Field(default=None, max_length=MAX_PROTOCOL_TEXT)
    extraction: ExtractionSnapshot | None = None


class ProtocolTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    version: int
    description: str
    raw_note_template: str
    condition_block: ConditionBlock
    source_experiment_id: int | None
    author: str
    created_at: datetime
    version_label: str = ""
    #: ``version_label`` or ``v<version>`` — what the screens show.
    display_version: str = ""
    #: Executable steps (stored, or derived from the note when none were stored).
    steps: list[ProtocolStep] = []
    steps_derived: bool = False
    #: Pasted original text (empty when the template was not created from a paste).
    source_text: str = ""
    extraction: ExtractionReview | None = None


class ProtocolTemplateList(BaseModel):
    project_id: int
    total: int
    items: list[ProtocolTemplateOut]


# ------------------------------------------------------------ protocol lineage


class ProtocolVersionRef(BaseModel):
    """Compact reference to one protocol template version."""

    template_id: int
    name: str
    version: int
    display_version: str
    created_at: datetime
    author: str
    source_experiment_id: int | None = None
    source_experiment_code: str | None = None


class ConditionValueChange(BaseModel):
    """One condition key that differs between two condition blocks (values copied)."""

    key: str
    label: str
    unit: str | None = None
    kind: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None


class ProtocolDiff(BaseModel):
    """Condition-level difference between two protocol versions (``a`` → ``b``)."""

    a: ProtocolVersionRef
    b: ProtocolVersionRef
    changes: list[ConditionValueChange]
    unchanged_keys: list[str]


class ProtocolUse(BaseModel):
    """An experiment recorded with a protocol version, and where it departed from it."""

    experiment_id: int
    code: str
    title: str
    author: str
    performed_on: date
    deviations: list[ConditionValueChange] = []


class ProtocolVersionNode(BaseModel):
    """One version in a protocol's lineage."""

    template: ProtocolVersionRef
    description: str
    changes_from_previous: list[ConditionValueChange]
    experiments: list[ProtocolUse]
    #: Earliest / latest ``performed_on`` of the experiments recorded with this version.
    first_used_on: date | None = None
    last_used_on: date | None = None


class ProtocolLineageItem(BaseModel):
    """All versions of one protocol name, oldest first."""

    name: str
    versions: list[ProtocolVersionNode]


class ProtocolLineage(BaseModel):
    project_id: int
    lineages: list[ProtocolLineageItem]


# ---------------------------------------------------------------- protocol runs

RunStatus = Literal["in_progress", "completed"]
#: ``check``/``uncheck`` a step, record an ``actual`` condition value (``value=None``
#: reverts to the planned value), or a free ``note`` on what was done differently.
RunEntryKind = Literal["check", "uncheck", "actual", "note"]


class ProtocolRunCreate(BaseModel):
    operator: str = Field(default="", max_length=100)


class ProtocolRunEntryCreate(BaseModel):
    """One append-only event of a run (stored immutably, audited)."""

    kind: RunEntryKind
    step_index: int = Field(ge=0)
    key: str | None = Field(default=None, max_length=64)
    value: str | float | None = None
    note: str = Field(default="", max_length=1000)


class RunCondition(BaseModel):
    """Planned value of a condition in a step and, if recorded, the actual value."""

    key: str
    label: str
    unit: str | None = None
    value_type: Literal["number", "text", "choice"] = "text"
    planned: Any = None
    actual: Any = None
    deviated: bool = False
    note: str = ""


class RunStep(BaseModel):
    index: int
    title: str
    detail: str = ""
    done: bool = False
    done_at: datetime | None = None
    conditions: list[RunCondition] = []
    notes: list[str] = []


class RunDeviation(BaseModel):
    """One difference from the protocol: a changed value, a note, or a step not checked."""

    step_index: int
    step_title: str
    kind: Literal["value", "note", "skipped"]
    key: str | None = None
    label: str | None = None
    unit: str | None = None
    planned: Any = None
    actual: Any = None
    note: str = ""


class ProtocolRunOut(BaseModel):
    """Current state of a run, folded from its append-only entries."""

    id: int
    project_id: int
    template: ProtocolVersionRef
    operator: str
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    experiment_id: int | None = None
    steps: list[RunStep]
    #: Value changes and notes (and, once completed, unchecked steps).
    deviations: list[RunDeviation]
    done_count: int
    step_count: int
    entry_count: int
    #: First step not yet checked (``None`` when every step is checked).
    current_step_index: int | None = None


class ProtocolRunList(BaseModel):
    items: list[ProtocolRunOut]


class ProtocolRunComplete(BaseModel):
    """Turn a run into an experiment record. ``dry_run`` previews without saving."""

    code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=100)
    performed_on: date
    parent_experiment_id: int | None = None
    observations: str = Field(default="", max_length=10_000)
    dry_run: bool = False


class ProtocolRunCompletion(BaseModel):
    """The experiment the run becomes: condition block with actual values + note."""

    run: ProtocolRunOut
    experiment: ExperimentCreate
    experiment_id: int | None = None
    deviations: list[RunDeviation]
    dry_run: bool


# ------------------------------------------------------------- field metadata

#: Human-readable (Korean) labels for known condition-block keys.
CONDITION_FIELD_LABELS: dict[str, str] = {
    "matrix": "매트릭스",
    "sample_mass_g": "시료량 (g)",
    "extraction_solvent": "추출 용매",
    "extraction_volume_ml": "추출 용매량 (mL)",
    "extraction_time_min": "추출 시간 (min)",
    "ph": "pH",
    "buffer": "완충염",
    "cleanup_sorbent": "정제 흡착제 (d-SPE)",
    "column": "컬럼",
    "column_temp_c": "컬럼 온도 (°C)",
    "internal_standard": "내부표준물질",
    "calibration_weighting": "검량선 가중",
    "instrument": "기기",
}

#: Units of known numeric condition keys (unit is part of the key's contract).
CONDITION_FIELD_UNITS: dict[str, str] = {
    "sample_mass_g": "g",
    "extraction_volume_ml": "mL",
    "extraction_time_min": "min",
    "column_temp_c": "°C",
}
