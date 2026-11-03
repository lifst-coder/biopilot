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
    content: str = Field(min_length=1, description="Raw CSV text (UTF-8, header row first)")
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


# ------------------------------------------------------------ protocol templates


class ProtocolTemplateCreate(BaseModel):
    """Reusable protocol. Saving an existing name creates a new version."""

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    raw_note_template: str | None = None
    condition_block: ConditionBlock | None = None
    source_experiment_id: int | None = None
    author: str = ""


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


class ProtocolTemplateList(BaseModel):
    project_id: int
    total: int
    items: list[ProtocolTemplateOut]


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
