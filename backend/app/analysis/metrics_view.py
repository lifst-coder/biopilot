"""Light views of stored results: only the fields headline metrics read (internal).

A stored ``AnalysisResult.output`` carries everything the charts and reports need — a
calibration result averages ~80 KB (fit lines, residuals, the fits of every weighting).
:func:`app.analysis.service.get_metrics` reads a dozen scalars from it. Building the full
output models for that dominated Records and the failure archive (PERFORMANCE.md), so
metrics validate the stored JSON text directly into these subset models instead:
``extra="ignore"`` skips every other field without materialising it.

Each view field has exactly the type of the same field in :mod:`app.analysis.schemas`,
so the values (and therefore the metrics) are identical to the ones read through the
full models — ``app/analysis/tests/test_batch_equivalence.py`` checks this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.analysis.schemas import QCFlag, ResultKind, WeightingName


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RecoveryRowView(_View):
    analyte: str
    recovery_pct: float


class GrubbsView(_View):
    is_outlier: bool


class RecoveryGroupView(_View):
    grubbs: GrubbsView | None = None


class UncertaintyView(_View):
    analyte: str
    expanded_pct: float


class RecoveryView(_View):
    kind: Literal["recovery"] = "recovery"
    overall_mean_pct: float
    overall_rsd_pct: float
    n: int
    groups: list[RecoveryGroupView]
    rows: list[RecoveryRowView]
    uncertainty: list[UncertaintyView] = []


class CalibrationAnalyteView(_View):
    analyte: str
    r_squared: float
    max_abs_back_calc_error_pct: float


class CalibrationView(_View):
    kind: Literal["calibration"] = "calibration"
    weighting: WeightingName
    analytes: list[CalibrationAnalyteView]


class ISResponseView(_View):
    kind: Literal["is_response"] = "is_response"
    injections: list[Any]  # only counted
    flagged_count: int


class MatrixEffectAnalyteView(_View):
    analyte: str
    matrix_effect_pct: float


class MatrixEffectView(_View):
    kind: Literal["matrix_effect"] = "matrix_effect"
    analytes: list[MatrixEffectAnalyteView]


class LimitsAnalyteView(_View):
    analyte: str
    primary_method: Literal["residual_sd", "intercept_sd", "low_level_replicates"]
    lod: float
    loq: float


class LimitsView(_View):
    kind: Literal["limits"] = "limits"
    unit: str = "ng/mL"
    analytes: list[LimitsAnalyteView]


class IonRatioView(_View):
    kind: Literal["ion_ratio"] = "ion_ratio"
    flagged_count: int


OutputView = Annotated[
    CalibrationView | RecoveryView | ISResponseView | MatrixEffectView | LimitsView | IonRatioView,
    Field(discriminator="kind"),
]
OUTPUT_VIEW: TypeAdapter[OutputView] = TypeAdapter(OutputView)


@dataclass(frozen=True)
class ResultView:
    """The parts of one stored result that headline metrics use."""

    id: int
    kind: ResultKind
    method_version: str
    parameters: dict[str, Any]
    flags: list[QCFlag]
    output: OutputView
