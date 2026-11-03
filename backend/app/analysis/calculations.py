"""Pure, deterministic calculation functions (no I/O, no database).

Conventions
-----------
* Response ratio ``R = analyte_area / is_area`` (internal-standard normalisation).
* Weighted least squares ``R = intercept + slope * x`` with weights ``1``, ``1/x`` or ``1/x²``.
* Reported R² is the *weighted* coefficient of determination.
* Recovery % = measured concentration / spiked concentration × 100, where the measured
  sample concentration (ng/g) = extract concentration (ng/mL) × extraction volume (mL) /
  sample mass (g).
* Matrix effect % = (slope_matrix / slope_solvent − 1) × 100 (absolute areas, no IS).

Every function is covered by unit tests in ``app/analysis/tests/test_calculations.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats

Weighting = Literal["none", "1/x", "1/x2"]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class LinearFit:
    """Result of a (weighted) straight-line fit."""

    slope: float
    intercept: float
    r_squared: float
    n: int
    weighting: Weighting

    def predict_x(self, y: FloatArray) -> FloatArray:
        """Invert the fit: concentration from response."""
        return (y - self.intercept) / self.slope


def weights_for(x: FloatArray, weighting: Weighting) -> FloatArray:
    """Weights for WLS. ``x`` must be strictly positive for 1/x and 1/x²."""
    if weighting == "none":
        return np.ones_like(x, dtype=float)
    if np.any(x <= 0):
        raise ValueError("1/x weighting requires positive concentrations")
    if weighting == "1/x":
        return np.asarray(1.0 / x, dtype=float)
    return np.asarray(1.0 / np.square(x), dtype=float)


def fit_line(x: FloatArray, y: FloatArray, weighting: Weighting = "none") -> LinearFit:
    """Weighted least-squares line through ``(x, y)``."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("need at least two paired points")
    if np.unique(x).size < 2:
        raise ValueError("need at least two distinct x values")
    w = weights_for(x, weighting)
    xw = float(np.sum(w * x) / np.sum(w))
    yw = float(np.sum(w * y) / np.sum(w))
    sxx = float(np.sum(w * (x - xw) ** 2))
    sxy = float(np.sum(w * (x - xw) * (y - yw)))
    slope = sxy / sxx
    intercept = yw - slope * xw
    residual = y - (intercept + slope * x)
    ss_res = float(np.sum(w * residual**2))
    ss_tot = float(np.sum(w * (y - yw) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return LinearFit(slope=slope, intercept=intercept, r_squared=r2, n=len(x), weighting=weighting)


def summary_stats(values: FloatArray) -> tuple[float, float, float]:
    """Return ``(mean, sd, rsd%)`` with sample SD (ddof=1; SD=0 for n=1)."""
    if values.size == 0:
        raise ValueError("empty sample")
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    rsd = sd / mean * 100.0 if mean != 0 else float("nan")
    return mean, sd, rsd


# ---------------------------------------------------------------- calibration


@dataclass(frozen=True)
class BackCalcLevel:
    level: float
    mean_back_calculated: float
    accuracy_pct: float


@dataclass(frozen=True)
class AnalyteCalibration:
    analyte: str
    fit: LinearFit
    back_calc: list[BackCalcLevel]

    @property
    def max_abs_error_pct(self) -> float:
        return max(abs(b.accuracy_pct - 100.0) for b in self.back_calc)


def response_ratio(frame: pd.DataFrame) -> FloatArray:
    """Analyte / IS area ratio as float array."""
    area = frame["analyte_area"].to_numpy(dtype=float)
    is_area = frame["is_area"].to_numpy(dtype=float)
    return np.asarray(area / is_area, dtype=float)


def calibrate(frame: pd.DataFrame, weighting: Weighting) -> dict[str, AnalyteCalibration]:
    """Fit one IS-normalised calibration line per analyte with back-calculated accuracy."""
    result: dict[str, AnalyteCalibration] = {}
    for analyte, group in frame.groupby("analyte", sort=True):
        x = group["level_ng_ml"].to_numpy(float)
        y = response_ratio(group)
        fit = fit_line(x, y, weighting)
        back = fit.predict_x(y)
        levels: list[BackCalcLevel] = []
        for level in np.unique(x):
            mask = x == level
            mean_bc = float(np.mean(back[mask]))
            levels.append(
                BackCalcLevel(
                    level=float(level),
                    mean_back_calculated=mean_bc,
                    accuracy_pct=mean_bc / float(level) * 100.0,
                )
            )
        result[str(analyte)] = AnalyteCalibration(str(analyte), fit, levels)
    return result


def weighting_error_sum(frame: pd.DataFrame, weighting: Weighting) -> float:
    """Σ|%RE| of back-calculated levels over all analytes — lower is better."""
    cal = calibrate(frame, weighting)
    return float(sum(abs(b.accuracy_pct - 100.0) for c in cal.values() for b in c.back_calc))


# ------------------------------------------------------------------- recovery


@dataclass(frozen=True)
class RecoveryRow:
    injection_id: str
    sample_id: str
    analyte: str
    spike_ng_g: float
    measured_ng_g: float
    recovery_pct: float


@dataclass(frozen=True)
class RecoveryGroup:
    analyte: str
    spike_ng_g: float
    n: int
    mean_pct: float
    sd_pct: float
    rsd_pct: float


def compute_recovery(
    frame: pd.DataFrame,
    calibration: dict[str, AnalyteCalibration],
    *,
    extraction_volume_ml: float,
    sample_mass_g: float,
) -> tuple[list[RecoveryRow], list[RecoveryGroup]]:
    """Per-injection recoveries and per (analyte, spike level) statistics."""
    if sample_mass_g <= 0 or extraction_volume_ml <= 0:
        raise ValueError("sample mass and extraction volume must be positive")
    factor = extraction_volume_ml / sample_mass_g
    rows: list[RecoveryRow] = []
    for record in frame.to_dict(orient="records"):
        analyte = str(record["analyte"])
        if analyte not in calibration:
            raise ValueError(f"no calibration for analyte {analyte}")
        fit = calibration[analyte].fit
        ratio = float(record["analyte_area"]) / float(record["is_area"])
        conc_extract = (ratio - fit.intercept) / fit.slope
        measured = conc_extract * factor
        spike = float(record["spike_ng_g"])
        rows.append(
            RecoveryRow(
                injection_id=str(record["injection_id"]),
                sample_id=str(record["sample_id"]),
                analyte=analyte,
                spike_ng_g=spike,
                measured_ng_g=measured,
                recovery_pct=measured / spike * 100.0,
            )
        )
    groups: list[RecoveryGroup] = []
    keys = sorted({(r.analyte, r.spike_ng_g) for r in rows})
    for analyte, spike in keys:
        values = np.array(
            [r.recovery_pct for r in rows if r.analyte == analyte and r.spike_ng_g == spike]
        )
        mean, sd, rsd = summary_stats(values)
        groups.append(RecoveryGroup(analyte, spike, int(values.size), mean, sd, rsd))
    return rows, groups


# ---------------------------------------------------------------- IS response


@dataclass(frozen=True)
class ISInjection:
    injection_id: str
    sample_id: str
    is_area: float
    response_pct: float


def compute_is_response(
    calibration_frame: pd.DataFrame, sample_frame: pd.DataFrame
) -> tuple[float, list[ISInjection]]:
    """IS area of each sample injection as % of the mean calibration IS area.

    Rows are de-duplicated per ``injection_id`` (long-format CSVs repeat the IS area
    once per analyte).
    """
    cal_is = calibration_frame.drop_duplicates("injection_id")["is_area"].to_numpy(float)
    reference = float(np.mean(cal_is))
    injections: list[ISInjection] = []
    for record in sample_frame.drop_duplicates("injection_id").to_dict(orient="records"):
        area = float(record["is_area"])
        injections.append(
            ISInjection(
                injection_id=str(record["injection_id"]),
                sample_id=str(record["sample_id"]),
                is_area=area,
                response_pct=area / reference * 100.0,
            )
        )
    return reference, injections


# --------------------------------------------------------------- matrix effect


@dataclass(frozen=True)
class MatrixEffect:
    analyte: str
    slope_solvent: float
    slope_matrix: float
    matrix_effect_pct: float


def compute_matrix_effect(frame: pd.DataFrame) -> list[MatrixEffect]:
    """Slope-ratio matrix effect per analyte from solvent vs matrix-matched curves."""
    out: list[MatrixEffect] = []
    for analyte, group in frame.groupby("analyte", sort=True):
        fits: dict[str, LinearFit] = {}
        for curve in ("solvent", "matrix"):
            part = group[group["curve"] == curve]
            if part.empty:
                raise ValueError(f"{analyte}: missing {curve} curve")
            fits[curve] = fit_line(
                part["level_ng_ml"].to_numpy(float), part["analyte_area"].to_numpy(float)
            )
        me = (fits["matrix"].slope / fits["solvent"].slope - 1.0) * 100.0
        out.append(MatrixEffect(str(analyte), fits["solvent"].slope, fits["matrix"].slope, me))
    return out


# ------------------------------------------------------------------ comparison


@dataclass(frozen=True)
class WelchResult:
    t_statistic: float
    p_value: float
    mean_a: float
    mean_b: float
    n_a: int
    n_b: int


def welch_t_test(a: FloatArray, b: FloatArray) -> WelchResult:
    """Two-sided Welch's t-test (unequal variances)."""
    if a.size < 2 or b.size < 2:
        raise ValueError("each sample needs at least two values")
    res = stats.ttest_ind(a, b, equal_var=False)
    return WelchResult(
        t_statistic=float(res.statistic),
        p_value=float(res.pvalue),
        mean_a=float(np.mean(a)),
        mean_b=float(np.mean(b)),
        n_a=int(a.size),
        n_b=int(b.size),
    )
