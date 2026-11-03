"""Pydantic schemas (API contract + cross-module DTOs) for the ELN layer."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DatasetKind = Literal["calibration", "recovery", "matrix_effect", "other"]

#: Required CSV columns per dataset kind. This is the ingestion contract that
#: Analysis relies on. Numeric columns are validated as numbers at upload time.
DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    "calibration": ("injection_id", "level_ng_ml", "analyte", "analyte_area", "is_area"),
    "recovery": ("injection_id", "sample_id", "analyte", "spike_ng_g", "analyte_area", "is_area"),
    "matrix_effect": ("injection_id", "curve", "level_ng_ml", "analyte", "analyte_area"),
    "other": (),
}

DATASET_NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {"level_ng_ml", "analyte_area", "is_area", "spike_ng_g"}
)


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
    """Display metadata for a condition-block key."""

    key: str
    label: str


class Attachment(BaseModel):
    """Metadata of a non-tabular attachment (chromatogram image, PDF, ...)."""

    name: str
    media_type: str
    description: str = ""


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


class ExperimentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, examples=["#025"])
    title: str = Field(min_length=1, max_length=200)
    author: str = ""
    performed_on: date
    parent_experiment_id: int | None = None
    raw_note: str
    condition_block: ConditionBlock
    attachments: list[Attachment] = []


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


class DatasetCreate(BaseModel):
    kind: DatasetKind
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, description="Raw CSV text (UTF-8, header row first)")


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


class DatasetPreview(BaseModel):
    dataset: DatasetOut
    rows: list[dict[str, Any]]
    truncated: bool


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
