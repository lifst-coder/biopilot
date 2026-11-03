"""Pydantic schemas for analysis results (API contract + cross-module DTOs).

Each result kind has a typed ``output`` model with a ``kind`` discriminator so the
generated TypeScript client gets a proper discriminated union.

Compatibility rule: fields added after the first release carry defaults so results
stored by older method versions still validate when read back.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResultKind = Literal[
    "calibration", "recovery", "is_response", "matrix_effect", "limits", "ion_ratio"
]
WeightingName = Literal["none", "1/x", "1/x2"]
Severity = Literal["info", "warning", "critical"]
FlagCode = Literal[
    "recovery_out_of_range",
    "recovery_rsd_high",
    "calibration_r2_low",
    "calibration_back_calc_error",
    "is_suppression",
    "is_enhancement",
    "matrix_effect_significant",
    "outlier_suspected",
    "uncertainty_high",
    "ion_ratio_out_of_range",
    "loq_above_lowest_level",
    "calibration_type_unsupported",
]
#: Contract domain of the condition-block key ``calibration_type`` (shared with Partner/ELN).
#: Analysis quantifies ``solvent`` and ``matrix-matched``; ``standard-addition`` is a valid
#: protocol value that Analysis does **not** support yet and flags explicitly.
CalibrationTypeValue = Literal["solvent", "matrix-matched", "standard-addition"]
CALIBRATION_TYPE_VALUES: tuple[str, ...] = ("solvent", "matrix-matched", "standard-addition")
SUPPORTED_CALIBRATION_TYPES: tuple[str, ...] = ("solvent", "matrix-matched")
QCStatus = Literal["pass", "warning", "fail", "not_analyzed"]
ReportFormat = Literal["markdown", "csv"]


class AcceptanceCriteria(BaseModel):
    """Thresholds and method settings used for QC flags (SANTE/11312/2021 defaults).

    Stored per project as immutable versions (see ``ProjectCriteria``); every flag
    records the version it was judged against.
    """

    source: str = "SANTE/11312/2021"
    recovery_min_pct: float = Field(default=70.0, ge=0)
    recovery_max_pct: float = Field(default=120.0, gt=0)
    rsd_max_pct: float = Field(default=20.0, gt=0)
    r_squared_min: float = Field(default=0.99, gt=0, le=1)
    back_calc_tolerance_pct: float = Field(default=20.0, gt=0)
    is_response_min_pct: float = Field(default=50.0, ge=0)
    is_response_max_pct: float = Field(default=150.0, gt=0)
    matrix_effect_abs_max_pct: float = Field(default=20.0, gt=0)
    expanded_uncertainty_max_pct: float = Field(
        default=50.0, gt=0, description="Max relative expanded uncertainty U (k·u_c), %"
    )
    ion_ratio_tolerance_pct: float = Field(
        default=30.0, gt=0, description="Max |ion-ratio deviation| from standards, %"
    )
    lod_k: float = Field(default=3.0, gt=0, description="LOD = k·σ/b (IUPAC 3; ICH 3.3)")
    lod_range_factor: float = Field(
        default=10.0,
        ge=1,
        description="LOD/LOQ regression uses levels ≤ factor × lowest level (min 3 levels)",
    )
    loq_k: float = Field(default=10.0, gt=0, description="LOQ = k·σ/b (IUPAC/ICH 10)")
    grubbs_alpha: float = Field(default=0.05, gt=0, lt=1, description="Grubbs test α")
    heteroscedasticity_alpha: float = Field(
        default=0.01, gt=0, lt=1, description="F-test α for variance homogeneity"
    )
    comparison_alpha: float = Field(
        default=0.05, gt=0, lt=1, description="α for comparison tests (after Holm)"
    )
    coverage_factor: float = Field(default=2.0, gt=0, description="k for expanded U")
    spike_uncertainty_pct: float = Field(
        default=0.0, ge=0, description="u(C_ref): relative standard uncertainty of spikes, %"
    )

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> AcceptanceCriteria:
        if self.recovery_min_pct >= self.recovery_max_pct:
            raise ValueError("recovery_min_pct must be below recovery_max_pct")
        if self.is_response_min_pct >= self.is_response_max_pct:
            raise ValueError("is_response_min_pct must be below is_response_max_pct")
        if self.lod_k >= self.loq_k:
            raise ValueError("lod_k must be below loq_k")
        return self


class QCFlag(BaseModel):
    """Deterministic QC check outcome. ``value`` is always computed from stored data."""

    code: FlagCode
    severity: Severity
    analyte: str | None = None
    value: float
    threshold_low: float | None = None
    threshold_high: float | None = None
    context: dict[str, Any] = {}
    criteria_version: str | None = Field(
        default=None, description="Label of the criteria version used for this judgement"
    )


class MethodDoc(BaseModel):
    """Formulas, assumptions and references of one computation (stored with results)."""

    kind: str
    version: str
    title: str
    formulas: list[str]
    assumptions: list[str]
    references: list[str] = []


# ---------------------------------------------------------------- outputs


class BackCalcLevelOut(BaseModel):
    level: float
    mean_back_calculated: float
    accuracy_pct: float


class CalibrationPoint(BaseModel):
    level: float
    response_ratio: float


class ResidualOut(BaseModel):
    """One calibration injection and its residuals (all computed in the backend)."""

    injection_id: str
    level: float
    response_ratio: float
    predicted: float
    residual: float
    back_calculated: float
    relative_error_pct: float = Field(description="%RE = (x̂ − x)/x × 100")
    standardized_residual: float | None = Field(
        default=None, description="√w·(y − ŷ)/s (weighted standardized residual)"
    )


class CalibrationFitOut(BaseModel):
    """The same calibration data fitted with one weighting (for the weighting toggle)."""

    weighting: WeightingName
    slope: float
    intercept: float
    r_squared: float
    residual_sd: float | None = None
    se_slope: float | None = None
    se_intercept: float | None = None
    max_abs_back_calc_error_pct: float
    sum_abs_relative_error_pct: float
    back_calc: list[BackCalcLevelOut]
    fit_line: list[CalibrationPoint]
    residuals: list[ResidualOut]


class HeteroscedasticityOut(BaseModel):
    """F-test of response variance at the highest vs lowest calibration level (ANA-5)."""

    level_low: float
    level_high: float
    n_low: int
    n_high: int
    var_low: float
    var_high: float
    f_statistic: float
    f_critical: float
    p_value: float
    alpha: float
    significant: bool


class AnalyteCalibrationOut(BaseModel):
    analyte: str
    slope: float
    intercept: float
    r_squared: float
    n: int
    weighting: WeightingName
    max_abs_back_calc_error_pct: float
    back_calc: list[BackCalcLevelOut]
    points: list[CalibrationPoint]
    fit_line: list[CalibrationPoint] = Field(
        description="Fitted response ratio at each calibration level (for plotting)"
    )
    residual_sd: float | None = None
    se_slope: float | None = None
    se_intercept: float | None = None
    residuals: list[ResidualOut] = []
    fits: list[CalibrationFitOut] = Field(
        default=[], description="Fits for every weighting scheme (none, 1/x, 1/x2)"
    )
    heteroscedasticity: HeteroscedasticityOut | None = None


class WeightingComparison(BaseModel):
    weighting: WeightingName
    sum_abs_relative_error_pct: float


class CalibrationOutput(BaseModel):
    kind: Literal["calibration"] = "calibration"
    weighting: WeightingName
    analytes: list[AnalyteCalibrationOut]
    weighting_comparison: list[WeightingComparison]
    calibration_type: str = "solvent"
    curve_used: str = Field(
        default="dataset", description="solvent | matrix rows of a `curve` column, or dataset"
    )
    heteroscedastic_analytes: list[str] = Field(
        default=[], description="Analytes whose F-test rejects constant variance"
    )
    method: MethodDoc | None = None


class RecoveryRowOut(BaseModel):
    injection_id: str
    sample_id: str
    analyte: str
    spike_ng_g: float
    measured_ng_g: float
    recovery_pct: float
    recovery_no_is_pct: float | None = Field(
        default=None, description="Recovery from an absolute-area calibration (no IS)"
    )


class GrubbsOut(BaseModel):
    """Two-sided Grubbs test of one replicate group (flag only, data never removed)."""

    n: int
    g_statistic: float
    g_critical: float
    alpha: float
    suspect_injection_id: str
    suspect_value: float
    is_outlier: bool


class RecoveryGroupOut(BaseModel):
    analyte: str
    spike_ng_g: float
    n: int
    mean_pct: float
    sd_pct: float
    rsd_pct: float
    mean_no_is_pct: float | None = None
    grubbs: GrubbsOut | None = None


class UncertaintyOut(BaseModel):
    """Relative expanded measurement uncertainty of one analyte (ANA-4), %."""

    analyte: str
    levels: int
    u_rw_pct: float
    rms_bias_pct: float
    u_cref_pct: float
    u_bias_pct: float
    u_combined_pct: float
    coverage_factor: float
    expanded_pct: float


class RecoveryOutput(BaseModel):
    kind: Literal["recovery"] = "recovery"
    overall_mean_pct: float
    overall_rsd_pct: float
    n: int
    groups: list[RecoveryGroupOut]
    rows: list[RecoveryRowOut]
    uncertainty: list[UncertaintyOut] = []
    method: MethodDoc | None = None


class ISInjectionOut(BaseModel):
    injection_id: str
    sample_id: str
    is_area: float
    response_pct: float
    flagged: bool
    role: Literal["calibration", "sample"] = "sample"


class ISResponseOutput(BaseModel):
    kind: Literal["is_response"] = "is_response"
    reference_is_area: float
    injections: list[ISInjectionOut]
    flagged_count: int
    reference_is_rsd_pct: float | None = Field(
        default=None, description="RSD of the calibration IS areas (reference precision)"
    )
    calibration_injections: list[ISInjectionOut] = Field(
        default=[], description="Calibration injections in run order (IS trend)"
    )
    method: MethodDoc | None = None


class MatrixEffectOut(BaseModel):
    analyte: str
    slope_solvent: float
    slope_matrix: float
    matrix_effect_pct: float


class MatrixEffectOutput(BaseModel):
    kind: Literal["matrix_effect"] = "matrix_effect"
    analytes: list[MatrixEffectOut]
    method: MethodDoc | None = None


class LimitEstimateOut(BaseModel):
    method: Literal["residual_sd", "intercept_sd", "low_level_replicates"]
    sigma: float
    slope: float
    n: int
    lod: float
    loq: float
    max_level: float = Field(default=0.0, description="Highest calibration level used for σ")


class AnalyteLimitsOut(BaseModel):
    """LOD/LOQ of one analyte. ``lod``/``loq`` in ng/mL (extract), ``*_ng_g`` in sample."""

    analyte: str
    primary_method: Literal["residual_sd", "intercept_sd", "low_level_replicates"]
    lod: float
    loq: float
    lod_ng_g: float | None = None
    loq_ng_g: float | None = None
    lowest_level: float
    estimates: list[LimitEstimateOut]


class LimitsOutput(BaseModel):
    kind: Literal["limits"] = "limits"
    k_lod: float
    k_loq: float
    unit: str = "ng/mL"
    analytes: list[AnalyteLimitsOut]
    method: MethodDoc | None = None


class IonRatioRowOut(BaseModel):
    injection_id: str
    sample_type: str
    analyte: str
    ion_ratio: float
    reference_ratio: float
    deviation_pct: float
    flagged: bool


class IonRatioOutput(BaseModel):
    kind: Literal["ion_ratio"] = "ion_ratio"
    tolerance_pct: float
    rows: list[IonRatioRowOut]
    flagged_count: int
    method: MethodDoc | None = None


AnalysisOutput = Annotated[
    CalibrationOutput
    | RecoveryOutput
    | ISResponseOutput
    | MatrixEffectOutput
    | LimitsOutput
    | IonRatioOutput,
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


# ---------------------------------------------------------------- criteria versions


class CriteriaVersionOut(BaseModel):
    """One immutable version of a project's criteria (version 0 = built-in defaults)."""

    id: int | None
    project_id: int
    version: int
    label: str
    criteria: AcceptanceCriteria
    note: str = ""
    created_at: datetime | None = None


class CriteriaCreate(BaseModel):
    """Request body for a new criteria version."""

    criteria: AcceptanceCriteria
    note: str = Field(default="", max_length=500)


class ProjectCriteria(BaseModel):
    """Active criteria of a project plus its full version history (oldest first)."""

    project_id: int
    active: CriteriaVersionOut
    history: list[CriteriaVersionOut]


# ---------------------------------------------------------------- summaries


class AnalyteRecoverySummary(BaseModel):
    analyte: str
    mean_pct: float
    rsd_pct: float
    n: int


class AnalyteLimitsSummary(BaseModel):
    analyte: str
    lod: float
    loq: float
    unit: str
    method: str


class AnalyteVerdict(BaseModel):
    """Deterministic pass/fail per analyte: fail = any critical flag, warning = any other."""

    analyte: str
    status: Literal["pass", "warning", "fail"]
    failed_checks: list[FlagCode] = []
    warning_checks: list[FlagCode] = []


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
    limits: list[AnalyteLimitsSummary] = []
    expanded_uncertainty_pct: dict[str, float] = {}
    outlier_count: int | None = None
    ion_ratio_injections_flagged: int | None = None
    qc_status: QCStatus = "not_analyzed"
    qc_verdicts: list[AnalyteVerdict] = []
    criteria_versions: list[str] = []


class AnalyteDelta(BaseModel):
    """Per-analyte comparison; test fields are ``None`` when n < 2 on either side."""

    analyte: str
    mean_a_pct: float
    mean_b_pct: float
    delta_pct_points: float
    n_a: int | None = None
    n_b: int | None = None
    t_statistic: float | None = None
    df: float | None = None
    p_value: float | None = None
    p_holm: float | None = Field(default=None, description="Holm-adjusted p-value")
    significant: bool | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    cohens_d: float | None = None
    hedges_g: float | None = None


class RecoveryTTest(BaseModel):
    """Welch t-test on all recoveries. ``t = (x̄_a − x̄_b)/SE``; difference/CI/d are b − a."""

    t_statistic: float
    p_value: float
    n_a: int
    n_b: int
    mean_a: float | None = None
    mean_b: float | None = None
    sd_a: float | None = None
    sd_b: float | None = None
    df: float | None = None
    standard_error: float | None = None
    mean_difference: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    confidence: float | None = None
    cohens_d: float | None = None
    hedges_g: float | None = None


class MetricsComparison(BaseModel):
    """Numerical comparison of two experiments (b relative to a)."""

    experiment_a: int
    experiment_b: int
    metrics_a: ExperimentMetrics
    metrics_b: ExperimentMetrics
    recovery_delta_pct_points: float | None
    per_analyte: list[AnalyteDelta]
    recovery_t_test: RecoveryTTest | None
    alpha: float = 0.05
    significant_analytes: list[str] = []
    method: MethodDoc | None = None


class TrendPoint(BaseModel):
    """One experiment on the project recovery trend."""

    experiment_id: int
    code: str
    performed_on: str
    recovery_mean_pct: float | None
    recovery_rsd_pct: float | None
    flag_count: int = Field(description="QC flags needing attention (warning + critical)")
    info_flag_count: int = Field(
        default=0, description="Informational flags (severity info), not counted above"
    )
    source_result_ids: list[int]


class RunResponse(BaseModel):
    experiment_id: int
    results: list[AnalysisResultOut]
    created: int
    reused: int
    skipped: list[str]


# ------------------------------------------------- records across projects


class RecordExperiment(BaseModel):
    """One experiment's stored headline numbers inside a records group."""

    experiment_id: int
    project_id: int
    code: str
    title: str
    author: str
    performed_on: date
    recovery_mean_pct: float | None = None
    recovery_rsd_pct: float | None = None
    qc_status: QCStatus = "not_analyzed"
    source_result_ids: list[int] = []


class RecordGroup(BaseModel):
    """Experiments sharing one value (condition value, author or month).

    ``recovery_*`` summarise the stored mean recovery of the members that have one;
    ``fail_count`` counts members whose stored QC status is ``fail`` (any critical flag)
    and ``fail_ratio`` = fail_count / analyzed_count (members with stored results).
    """

    key: str
    value: Any = None
    experiments: list[RecordExperiment]
    experiment_count: int
    analyzed_count: int
    recovery_n: int
    recovery_min_pct: float | None = None
    recovery_median_pct: float | None = None
    recovery_max_pct: float | None = None
    fail_count: int
    fail_ratio: float | None = None


class ConditionRecords(BaseModel):
    """Every stored experiment grouped by the value of one condition key."""

    key: str
    project_ids: list[int]
    contains: str | None = None
    groups: list[RecordGroup] = Field(description="Largest group first")
    matched: RecordGroup | None = Field(
        default=None, description="All experiments whose value contains ``contains`` (pooled)"
    )


class OperatorPair(BaseModel):
    """Two experiments with identical condition blocks run by different people.

    Numbers are ``compare(a, b)`` (Welch t-test on all stored recovery rows, b − a).
    """

    experiment_a: RecordExperiment
    experiment_b: RecordExperiment
    days_apart: int
    condition_key_count: int = Field(description="Condition keys compared (all identical)")
    recovery_delta_pct_points: float | None = None
    p_value: float | None = None
    alpha: float = 0.05
    significant: bool | None = None
    significant_analytes: list[str] = []


class OperatorRecords(BaseModel):
    project_ids: list[int]
    window_days: int
    authors: list[RecordGroup] = Field(description="All experiments grouped by author")
    pairs: list[OperatorPair] = Field(description="Largest |Δ| first")


class RecordGap(BaseModel):
    """A stretch with no experiment at all in the selected projects."""

    start: date = Field(description="Last experiment date before the gap")
    end: date = Field(description="First experiment date after the gap")
    days: int
    before: list[RecordExperiment]
    after: list[RecordExperiment]


class PeriodRecords(BaseModel):
    project_ids: list[int]
    gap_days: int
    months: list[RecordGroup] = Field(description="Chronological, key = YYYY-MM")
    gaps: list[RecordGap]
