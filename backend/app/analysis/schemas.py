"""Pydantic schemas for analysis results (API contract + cross-module DTOs).

Each result kind has a typed ``output`` model with a ``kind`` discriminator so the
generated TypeScript client gets a proper discriminated union.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ResultKind = Literal["calibration", "recovery", "is_response", "matrix_effect"]
Severity = Literal["info", "warning", "critical"]
FlagCode = Literal[
    "recovery_out_of_range",
    "recovery_rsd_high",
    "calibration_r2_low",
    "calibration_back_calc_error",
    "is_suppression",
    "is_enhancement",
    "matrix_effect_significant",
]


class AcceptanceCriteria(BaseModel):
    """Thresholds used for QC flags. Exposed read-only via the API."""

    source: str = "SANTE/11312/2021"
    recovery_min_pct: float = 70.0
    recovery_max_pct: float = 120.0
    rsd_max_pct: float = 20.0
    r_squared_min: float = 0.99
    back_calc_tolerance_pct: float = 20.0
    is_response_min_pct: float = 50.0
    is_response_max_pct: float = 150.0
    matrix_effect_abs_max_pct: float = 20.0


class QCFlag(BaseModel):
    """Deterministic QC check outcome. ``value`` is always computed from stored data."""

    code: FlagCode
    severity: Severity
    analyte: str | None = None
    value: float
    threshold_low: float | None = None
    threshold_high: float | None = None
    context: dict[str, Any] = {}


# ---------------------------------------------------------------- outputs


class BackCalcLevelOut(BaseModel):
    level: float
    mean_back_calculated: float
    accuracy_pct: float


class CalibrationPoint(BaseModel):
    level: float
    response_ratio: float


class AnalyteCalibrationOut(BaseModel):
    analyte: str
    slope: float
    intercept: float
    r_squared: float
    n: int
    weighting: Literal["none", "1/x", "1/x2"]
    max_abs_back_calc_error_pct: float
    back_calc: list[BackCalcLevelOut]
    points: list[CalibrationPoint]
    fit_line: list[CalibrationPoint] = Field(
        description="Fitted response ratio at each calibration level (for plotting)"
    )


class WeightingComparison(BaseModel):
    weighting: Literal["none", "1/x", "1/x2"]
    sum_abs_relative_error_pct: float


class CalibrationOutput(BaseModel):
    kind: Literal["calibration"] = "calibration"
    weighting: Literal["none", "1/x", "1/x2"]
    analytes: list[AnalyteCalibrationOut]
    weighting_comparison: list[WeightingComparison]


class RecoveryRowOut(BaseModel):
    injection_id: str
    sample_id: str
    analyte: str
    spike_ng_g: float
    measured_ng_g: float
    recovery_pct: float


class RecoveryGroupOut(BaseModel):
    analyte: str
    spike_ng_g: float
    n: int
    mean_pct: float
    sd_pct: float
    rsd_pct: float


class RecoveryOutput(BaseModel):
    kind: Literal["recovery"] = "recovery"
    overall_mean_pct: float
    overall_rsd_pct: float
    n: int
    groups: list[RecoveryGroupOut]
    rows: list[RecoveryRowOut]


class ISInjectionOut(BaseModel):
    injection_id: str
    sample_id: str
    is_area: float
    response_pct: float
    flagged: bool


class ISResponseOutput(BaseModel):
    kind: Literal["is_response"] = "is_response"
    reference_is_area: float
    injections: list[ISInjectionOut]
    flagged_count: int


class MatrixEffectOut(BaseModel):
    analyte: str
    slope_solvent: float
    slope_matrix: float
    matrix_effect_pct: float


class MatrixEffectOutput(BaseModel):
    kind: Literal["matrix_effect"] = "matrix_effect"
    analytes: list[MatrixEffectOut]


AnalysisOutput = Annotated[
    CalibrationOutput | RecoveryOutput | ISResponseOutput | MatrixEffectOutput,
    Field(discriminator="kind"),
]


class AnalysisResultOut(BaseModel):
    """An immutable, stored analysis result with full provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    kind: ResultKind
    method_version: str
    input_dataset_ids: list[int]
    input_fingerprint: str
    parameters: dict[str, Any]
    output: AnalysisOutput
    flags: list[QCFlag]
    created_at: datetime


# ---------------------------------------------------------------- summaries


class AnalyteRecoverySummary(BaseModel):
    analyte: str
    mean_pct: float
    rsd_pct: float
    n: int


class ExperimentMetrics(BaseModel):
    """Headline numbers for one experiment, each traceable to ``source_result_ids``."""

    experiment_id: int
    analyzed: bool
    recovery_mean_pct: float | None = None
    recovery_rsd_pct: float | None = None
    recovery_n: int | None = None
    per_analyte_recovery: list[AnalyteRecoverySummary] = []
    min_r_squared: float | None = None
    max_abs_back_calc_error_pct: float | None = None
    calibration_weighting: str | None = None
    is_injections_total: int | None = None
    is_injections_flagged: int | None = None
    matrix_effect_pct: dict[str, float] = {}
    flags: list[QCFlag] = []
    source_result_ids: list[int] = []


class AnalyteDelta(BaseModel):
    analyte: str
    mean_a_pct: float
    mean_b_pct: float
    delta_pct_points: float


class RecoveryTTest(BaseModel):
    t_statistic: float
    p_value: float
    n_a: int
    n_b: int


class MetricsComparison(BaseModel):
    """Numerical comparison of two experiments (b relative to a)."""

    experiment_a: int
    experiment_b: int
    metrics_a: ExperimentMetrics
    metrics_b: ExperimentMetrics
    recovery_delta_pct_points: float | None
    per_analyte: list[AnalyteDelta]
    recovery_t_test: RecoveryTTest | None


class TrendPoint(BaseModel):
    experiment_id: int
    code: str
    performed_on: str
    recovery_mean_pct: float | None
    recovery_rsd_pct: float | None
    flag_count: int
    source_result_ids: list[int]


class RunResponse(BaseModel):
    experiment_id: int
    results: list[AnalysisResultOut]
    created: int
    reused: int
    skipped: list[str]
