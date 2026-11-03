"""Pure, deterministic calculation functions (no I/O, no database, no interpretation).

Conventions
-----------
* Response ratio ``R = analyte_area / is_area`` (internal-standard normalisation).
* Weighted least squares ``R = a + b·x`` with weights ``w = 1``, ``1/x`` or ``1/x²``.
* Reported R² is the *weighted* coefficient of determination.
* Recovery % = measured concentration / spiked concentration × 100, where the measured
  sample concentration (ng/g) = extract concentration (ng/mL) × extraction volume (mL) /
  sample mass (g).
* Matrix effect % = (slope_matrix / slope_solvent − 1) × 100 (absolute areas, no IS).
* LOD / LOQ = k·σ / b (IUPAC: k_D = 3, k_Q = 10; ICH Q2 uses 3.3 — configurable).
* Sample statistics use the unbiased SD (``ddof=1``).

The human-readable formula sheet that is stored with every result lives in
:mod:`app.analysis.methods`. Every function is covered by hand-calculated unit tests in
``app/analysis/tests/test_calculations.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats

Weighting = Literal["none", "1/x", "1/x2"]
WEIGHTINGS: tuple[Weighting, ...] = ("none", "1/x", "1/x2")
CalibrationType = Literal["solvent", "matrix-matched"]
CurveUsed = Literal["solvent", "matrix", "dataset"]
LimitsMethod = Literal["residual_sd", "intercept_sd", "low_level_replicates"]
FloatArray = NDArray[np.float64]


# ------------------------------------------------------------------ regression


@dataclass(frozen=True)
class LinearFit:
    """Result of a (weighted) straight-line fit ``y = intercept + slope·x``.

    ``residual_sd`` is the weighted residual standard deviation
    ``s = √(Σ wᵢ rᵢ² / (n − 2))`` (equal to the classic s_y/x for ``weighting="none"``);
    standard errors follow the WLS formulas ``SE(b) = s / √Sxx_w`` and
    ``SE(a) = s·√(1/Σw + x̄_w²/Sxx_w)``. All three are ``None`` when ``n = 2`` (df = 0).
    """

    slope: float
    intercept: float
    r_squared: float
    n: int
    weighting: Weighting
    residual_sd: float | None = None
    se_slope: float | None = None
    se_intercept: float | None = None

    def predict_x(self, y: FloatArray) -> FloatArray:
        """Invert the fit: concentration from response."""
        return np.asarray((y - self.intercept) / self.slope, dtype=float)

    def predict_y(self, x: FloatArray) -> FloatArray:
        """Fitted response at concentration ``x``."""
        return np.asarray(self.intercept + self.slope * x, dtype=float)


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
    """Weighted least-squares line through ``(x, y)``.

    ``b = Σw(x−x̄_w)(y−ȳ_w) / Σw(x−x̄_w)²``, ``a = ȳ_w − b·x̄_w`` with weighted means
    ``x̄_w = Σwx/Σw``. R² = 1 − Σw·r² / Σw(y−ȳ_w)².
    """
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("need at least two paired points")
    if np.unique(x).size < 2:
        raise ValueError("need at least two distinct x values")
    w = weights_for(x, weighting)
    sw = float(np.sum(w))
    xw = float(np.sum(w * x) / sw)
    yw = float(np.sum(w * y) / sw)
    sxx = float(np.sum(w * (x - xw) ** 2))
    sxy = float(np.sum(w * (x - xw) * (y - yw)))
    slope = sxy / sxx
    intercept = yw - slope * xw
    residual = y - (intercept + slope * x)
    ss_res = float(np.sum(w * residual**2))
    ss_tot = float(np.sum(w * (y - yw) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    n = len(x)
    s: float | None = None
    se_b: float | None = None
    se_a: float | None = None
    if n > 2:
        s = math.sqrt(ss_res / (n - 2))
        se_b = s / math.sqrt(sxx)
        se_a = s * math.sqrt(1.0 / sw + xw**2 / sxx)
    return LinearFit(
        slope=slope,
        intercept=intercept,
        r_squared=r2,
        n=n,
        weighting=weighting,
        residual_sd=s,
        se_slope=se_b,
        se_intercept=se_a,
    )


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
    """Mean back-calculated concentration of one calibration level."""

    level: float
    mean_back_calculated: float
    accuracy_pct: float


@dataclass(frozen=True)
class Residual:
    """One calibration point and its residuals.

    ``relative_error_pct`` (%RE) = (x̂ − x) / x × 100 with x̂ = (y − a) / b;
    ``standardized`` = √w·(y − ŷ) / s (``None`` when s is undefined or zero).
    """

    injection_id: str
    level: float
    response: float
    predicted: float
    residual: float
    back_calculated: float
    relative_error_pct: float
    standardized: float | None


@dataclass(frozen=True)
class AnalyteCalibration:
    """Calibration of one analyte with one weighting scheme."""

    analyte: str
    fit: LinearFit
    back_calc: list[BackCalcLevel]
    residuals: list[Residual]

    @property
    def max_abs_error_pct(self) -> float:
        """Largest |accuracy − 100| over calibration levels."""
        return max(abs(b.accuracy_pct - 100.0) for b in self.back_calc)

    @property
    def sum_abs_error_pct(self) -> float:
        """Σ|%RE| over level means (used to compare weightings)."""
        return float(sum(abs(b.accuracy_pct - 100.0) for b in self.back_calc))


def response_ratio(frame: pd.DataFrame) -> FloatArray:
    """Analyte / IS area ratio as float array."""
    area = frame["analyte_area"].to_numpy(dtype=float)
    is_area = frame["is_area"].to_numpy(dtype=float)
    return np.asarray(area / is_area, dtype=float)


def _response(frame: pd.DataFrame, use_is: bool) -> FloatArray:
    if use_is:
        return response_ratio(frame)
    return np.asarray(frame["analyte_area"].to_numpy(dtype=float), dtype=float)


def calibrate_analyte(
    analyte: str,
    injection_ids: list[str],
    x: FloatArray,
    y: FloatArray,
    weighting: Weighting,
) -> AnalyteCalibration:
    """Fit one analyte and compute back-calculation accuracy and per-point residuals."""
    fit = fit_line(x, y, weighting)
    back = fit.predict_x(y)
    predicted = fit.predict_y(x)
    w = weights_for(x, weighting)
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
    s = fit.residual_sd
    residuals = [
        Residual(
            injection_id=injection_ids[i],
            level=float(x[i]),
            response=float(y[i]),
            predicted=float(predicted[i]),
            residual=float(y[i] - predicted[i]),
            back_calculated=float(back[i]),
            relative_error_pct=float((back[i] - x[i]) / x[i] * 100.0),
            standardized=(float(math.sqrt(w[i]) * (y[i] - predicted[i]) / s) if s else None),
        )
        for i in range(len(x))
    ]
    return AnalyteCalibration(analyte, fit, levels, residuals)


def calibrate(
    frame: pd.DataFrame, weighting: Weighting, *, use_is: bool = True
) -> dict[str, AnalyteCalibration]:
    """Fit one calibration line per analyte (IS-normalised unless ``use_is=False``)."""
    result: dict[str, AnalyteCalibration] = {}
    for analyte, group in frame.groupby("analyte", sort=True):
        x = group["level_ng_ml"].to_numpy(float)
        y = _response(group, use_is)
        ids = [str(v) for v in group["injection_id"]]
        result[str(analyte)] = calibrate_analyte(str(analyte), ids, x, y, weighting)
    return result


def weighting_error_sum(frame: pd.DataFrame, weighting: Weighting) -> float:
    """Σ|%RE| of back-calculated levels over all analytes — lower is better."""
    cal = calibrate(frame, weighting)
    return float(sum(c.sum_abs_error_pct for c in cal.values()))


def select_calibration_curve(
    frame: pd.DataFrame, calibration_type: CalibrationType
) -> tuple[pd.DataFrame, CurveUsed]:
    """Pick the calibration rows to quantify with (ANA-2).

    A calibration CSV may carry an optional ``curve`` column (``solvent``/``matrix``).
    ``matrix-matched`` selects ``curve == "matrix"``, ``solvent`` selects ``curve ==
    "solvent"``. Without the column the whole dataset is used as declared (``"dataset"``).
    Raises ``ValueError`` when the requested curve is absent.
    """
    if "curve" not in frame.columns:
        return frame, "dataset"
    wanted: CurveUsed = "matrix" if calibration_type == "matrix-matched" else "solvent"
    part = frame[frame["curve"].astype(str).str.strip().str.lower() == wanted]
    if part.empty:
        raise ValueError(f"calibration dataset has no '{wanted}' curve rows")
    return part.reset_index(drop=True), wanted


# ---------------------------------------------------------------- F-test (ANA-5)


@dataclass(frozen=True)
class HeteroscedasticityTest:
    """One-sided F-test of response variance at the highest vs lowest level.

    ``F = s²_high / s²_low`` with df = (n_high − 1, n_low − 1);
    significant when ``F > F_crit(1 − α)`` → variance is not constant → weighting needed.
    """

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


def heteroscedasticity_f_test(
    x: FloatArray, y: FloatArray, alpha: float = 0.01
) -> HeteroscedasticityTest | None:
    """F-test on replicate responses at the extreme levels; ``None`` without replicates."""
    levels = np.unique(x)
    if levels.size < 2:
        return None
    low, high = float(levels[0]), float(levels[-1])
    y_low, y_high = y[x == low], y[x == high]
    if y_low.size < 2 or y_high.size < 2:
        return None
    var_low = float(np.var(y_low, ddof=1))
    var_high = float(np.var(y_high, ddof=1))
    if var_low <= 0:
        return None
    df_num, df_den = int(y_high.size - 1), int(y_low.size - 1)
    f = var_high / var_low
    f_crit = float(stats.f.ppf(1.0 - alpha, df_num, df_den))
    p = float(stats.f.sf(f, df_num, df_den))
    return HeteroscedasticityTest(
        level_low=low,
        level_high=high,
        n_low=int(y_low.size),
        n_high=int(y_high.size),
        var_low=var_low,
        var_high=var_high,
        f_statistic=f,
        f_critical=f_crit,
        p_value=p,
        alpha=alpha,
        significant=f > f_crit,
    )


# ---------------------------------------------------------------- LOD/LOQ (ANA-1)


@dataclass(frozen=True)
class LimitEstimate:
    """LOD/LOQ from one σ estimate: ``LOD = k_D·σ/b``, ``LOQ = k_Q·σ/b`` (ng/mL)."""

    method: LimitsMethod
    sigma: float
    slope: float
    n: int
    lod: float
    loq: float
    max_level: float


def low_range_mask(
    x: FloatArray, range_factor: float = 10.0, min_levels: int = 3
) -> NDArray[np.bool_]:
    """Points whose level is ≤ ``range_factor`` × the lowest level (≥ ``min_levels`` levels).

    LOD/LOQ from a regression should use calibration data near the limit (ICH Q2);
    on a wide, heteroscedastic range the full-range s_y/x is dominated by the top levels.
    """
    levels = np.unique(x)
    keep = levels[levels <= float(levels[0]) * range_factor]
    if keep.size < min_levels:
        keep = levels[:min_levels]
    return np.asarray(np.isin(x, keep), dtype=bool)


def detection_limits(
    x: FloatArray,
    y: FloatArray,
    *,
    k_lod: float = 3.0,
    k_loq: float = 10.0,
    replicate_slope: float | None = None,
    range_factor: float = 10.0,
) -> list[LimitEstimate]:
    """Every LOD/LOQ estimate the data supports.

    * ``residual_sd`` — σ = s_y/x of the unweighted OLS line over the low range
      (:func:`low_range_mask`), b = its slope.
    * ``intercept_sd`` — σ = SE(intercept) of the same OLS line.
    * ``low_level_replicates`` — σ = SD of the responses at the lowest level (n ≥ 2),
      b = ``replicate_slope`` (the reported calibration slope) or the OLS slope.

    Estimates with σ undefined (n = 2 points) are omitted.
    """
    mask = low_range_mask(x, range_factor)
    x_low_range, y_low_range = x[mask], y[mask]
    ols = fit_line(x_low_range, y_low_range, "none")
    if ols.slope <= 0:
        raise ValueError("LOD/LOQ require a positive calibration slope")
    top = float(np.max(x_low_range))
    out: list[LimitEstimate] = []

    def add(method: LimitsMethod, sigma: float, slope: float, n: int, max_level: float) -> None:
        out.append(
            LimitEstimate(
                method, sigma, slope, n, k_lod * sigma / slope, k_loq * sigma / slope, max_level
            )
        )

    if ols.residual_sd is not None:
        add("residual_sd", ols.residual_sd, ols.slope, ols.n, top)
    if ols.se_intercept is not None:
        add("intercept_sd", ols.se_intercept, ols.slope, ols.n, top)
    lowest = float(np.min(x))
    y_low = y[x == lowest]
    if y_low.size >= 2:
        slope = replicate_slope if replicate_slope and replicate_slope > 0 else ols.slope
        add("low_level_replicates", float(np.std(y_low, ddof=1)), slope, int(y_low.size), lowest)
    return out


def primary_limit(estimates: list[LimitEstimate], min_replicates: int = 3) -> LimitEstimate:
    """Reported estimate: low-level replicates if n ≥ ``min_replicates``, else residual SD."""
    by_method = {e.method: e for e in estimates}
    rep = by_method.get("low_level_replicates")
    if rep is not None and rep.n >= min_replicates:
        return rep
    fallback_order: tuple[LimitsMethod, ...] = (
        "residual_sd",
        "intercept_sd",
        "low_level_replicates",
    )
    for method in fallback_order:
        if method in by_method:
            return by_method[method]
    raise ValueError("no LOD/LOQ estimate available")


# ---------------------------------------------------------------- Grubbs (ANA-3)


@dataclass(frozen=True)
class GrubbsResult:
    """Two-sided Grubbs test for a single outlier.

    ``G = max|xᵢ − x̄| / s``;
    ``G_crit = (n−1)/√n · √(t² / (n − 2 + t²))`` with ``t = t(α/(2n), n − 2)``.
    """

    n: int
    g_statistic: float
    g_critical: float
    alpha: float
    suspect_index: int
    suspect_value: float
    is_outlier: bool


def grubbs_critical(n: int, alpha: float = 0.05) -> float:
    """Two-sided Grubbs critical value for sample size ``n`` (n ≥ 3)."""
    if n < 3:
        raise ValueError("Grubbs test needs n >= 3")
    t = float(stats.t.ppf(1.0 - alpha / (2 * n), n - 2))
    return (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))


def grubbs_test(values: FloatArray, alpha: float = 0.05) -> GrubbsResult | None:
    """Grubbs test on one replicate group; ``None`` when n < 3 or SD = 0."""
    n = int(values.size)
    if n < 3:
        return None
    sd = float(np.std(values, ddof=1))
    if sd == 0:
        return None
    dev = np.abs(values - float(np.mean(values)))
    idx = int(np.argmax(dev))
    g = float(dev[idx]) / sd
    g_crit = grubbs_critical(n, alpha)
    return GrubbsResult(n, g, g_crit, alpha, idx, float(values[idx]), g > g_crit)


# ------------------------------------------------------------------- recovery


@dataclass(frozen=True)
class RecoveryRow:
    """Recovery of one injection (with and without IS correction)."""

    injection_id: str
    sample_id: str
    analyte: str
    spike_ng_g: float
    measured_ng_g: float
    recovery_pct: float
    recovery_no_is_pct: float | None = None


@dataclass(frozen=True)
class RecoveryGroup:
    """Statistics of one (analyte, spike level) replicate group."""

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
    calibration_no_is: dict[str, AnalyteCalibration] | None = None,
) -> tuple[list[RecoveryRow], list[RecoveryGroup]]:
    """Per-injection recoveries and per (analyte, spike level) statistics.

    When ``calibration_no_is`` (absolute-area calibration) is given, each row also gets
    the recovery *without* IS correction, which shows what the IS normalisation changed.
    """
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
        measured = (ratio - fit.intercept) / fit.slope * factor
        spike = float(record["spike_ng_g"])
        no_is: float | None = None
        if calibration_no_is is not None and analyte in calibration_no_is:
            abs_fit = calibration_no_is[analyte].fit
            abs_measured = (float(record["analyte_area"]) - abs_fit.intercept) / abs_fit.slope
            no_is = abs_measured * factor / spike * 100.0
        rows.append(
            RecoveryRow(
                injection_id=str(record["injection_id"]),
                sample_id=str(record["sample_id"]),
                analyte=analyte,
                spike_ng_g=spike,
                measured_ng_g=measured,
                recovery_pct=measured / spike * 100.0,
                recovery_no_is_pct=no_is,
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


# -------------------------------------------------------- uncertainty (ANA-4)


@dataclass(frozen=True)
class Uncertainty:
    """Nordtest TR 537 style relative expanded uncertainty from recovery data (%).

    ``u(Rw) = pooled RSD = √(Σ(nᵢ−1)·RSDᵢ² / Σ(nᵢ−1))``;
    ``u(bias) = √(RMS_bias² + u(C_ref)²)`` with ``RMS_bias = √(Σ(R̄ᵢ − 100)² / m)``;
    ``u_c = √(u(Rw)² + u(bias)²)``, ``U = k·u_c``.
    """

    analyte: str
    levels: int
    u_rw_pct: float
    rms_bias_pct: float
    u_cref_pct: float
    u_bias_pct: float
    u_combined_pct: float
    coverage_factor: float
    expanded_pct: float


def recovery_uncertainty(
    analyte: str,
    groups: list[RecoveryGroup],
    *,
    coverage_factor: float = 2.0,
    u_cref_pct: float = 0.0,
) -> Uncertainty:
    """Expanded relative uncertainty of one analyte from its recovery groups."""
    mine = [g for g in groups if g.analyte == analyte]
    if not mine:
        raise ValueError(f"no recovery groups for {analyte}")
    dof = sum(g.n - 1 for g in mine)
    u_rw = math.sqrt(sum((g.n - 1) * g.rsd_pct**2 for g in mine) / dof) if dof > 0 else 0.0
    rms_bias = math.sqrt(sum((g.mean_pct - 100.0) ** 2 for g in mine) / len(mine))
    u_bias = math.sqrt(rms_bias**2 + u_cref_pct**2)
    u_c = math.sqrt(u_rw**2 + u_bias**2)
    return Uncertainty(
        analyte=analyte,
        levels=len(mine),
        u_rw_pct=u_rw,
        rms_bias_pct=rms_bias,
        u_cref_pct=u_cref_pct,
        u_bias_pct=u_bias,
        u_combined_pct=u_c,
        coverage_factor=coverage_factor,
        expanded_pct=coverage_factor * u_c,
    )


# ---------------------------------------------------------------- IS response


@dataclass(frozen=True)
class ISInjection:
    """IS area of one injection relative to the calibration mean."""

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
    reference, _ = calibration_is_reference(calibration_frame)
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


def calibration_is_reference(calibration_frame: pd.DataFrame) -> tuple[float, list[ISInjection]]:
    """Mean calibration IS area and each calibration injection as % of it (run order)."""
    unique = calibration_frame.drop_duplicates("injection_id")
    cal_is = unique["is_area"].to_numpy(float)
    reference = float(np.mean(cal_is))
    injections = [
        ISInjection(
            injection_id=str(r["injection_id"]),
            sample_id=f"STD {float(r['level_ng_ml']):g} ng/mL",
            is_area=float(r["is_area"]),
            response_pct=float(r["is_area"]) / reference * 100.0,
        )
        for r in unique.to_dict(orient="records")
    ]
    return reference, injections


# --------------------------------------------------------------- matrix effect


@dataclass(frozen=True)
class MatrixEffect:
    """Slope-ratio matrix effect of one analyte."""

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


# ------------------------------------------------------------- ion ratio (ANA-8)

ION_RATIO_COLUMNS: tuple[str, ...] = (
    "injection_id",
    "sample_type",
    "analyte",
    "quantifier_area",
    "qualifier_area",
)


@dataclass(frozen=True)
class IonRatioRow:
    """Qualifier/quantifier ratio of one injection vs the standards' mean ratio."""

    injection_id: str
    sample_type: str
    analyte: str
    ion_ratio: float
    reference_ratio: float
    deviation_pct: float


def compute_ion_ratios(frame: pd.DataFrame) -> list[IonRatioRow]:
    """Ion ratio = qualifier / quantifier; deviation = (ratio / reference − 1) × 100.

    The reference is the mean ratio of ``sample_type == "standard"`` injections of the
    same analyte (SANTE/11312/2021 §D12). Only non-standard injections are returned.
    """
    missing = [c for c in ION_RATIO_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"ion-ratio data is missing columns: {', '.join(missing)}")
    rows: list[IonRatioRow] = []
    kind = frame["sample_type"].astype(str).str.strip().str.lower()
    for analyte, group in frame.groupby("analyte", sort=True):
        ratios = group["qualifier_area"].to_numpy(float) / group["quantifier_area"].to_numpy(float)
        is_std = (kind.loc[group.index] == "standard").to_numpy()
        if not is_std.any():
            raise ValueError(f"{analyte}: no standard injections for the reference ion ratio")
        reference = float(np.mean(ratios[is_std]))
        for i, record in enumerate(group.to_dict(orient="records")):
            if is_std[i]:
                continue
            rows.append(
                IonRatioRow(
                    injection_id=str(record["injection_id"]),
                    sample_type=str(record["sample_type"]),
                    analyte=str(analyte),
                    ion_ratio=float(ratios[i]),
                    reference_ratio=reference,
                    deviation_pct=(float(ratios[i]) / reference - 1.0) * 100.0,
                )
            )
    return rows


# ------------------------------------------------------------------ comparison


@dataclass(frozen=True)
class WelchResult:
    """Welch two-sample comparison of ``b`` against ``a``.

    ``t = (x̄_a − x̄_b) / SE`` (sign kept from the original contract),
    ``SE = √(s_a²/n_a + s_b²/n_b)``, Welch–Satterthwaite df, two-sided p.
    ``mean_difference`` and the CI are for ``x̄_b − x̄_a``. Effect sizes are
    ``d = (x̄_b − x̄_a) / s_pooled`` and Hedges' ``g = d·(1 − 3/(4(n_a+n_b) − 9))``.
    """

    t_statistic: float
    p_value: float
    mean_a: float
    mean_b: float
    n_a: int
    n_b: int
    sd_a: float = 0.0
    sd_b: float = 0.0
    df: float = 0.0
    standard_error: float = 0.0
    mean_difference: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    confidence: float = 0.95
    cohens_d: float = 0.0
    hedges_g: float = 0.0


def pooled_sd(a: FloatArray, b: FloatArray) -> float:
    """``s_p = √(((n_a−1)s_a² + (n_b−1)s_b²) / (n_a + n_b − 2))``."""
    na, nb = a.size, b.size
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    return math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))


def welch_t_test(a: FloatArray, b: FloatArray, confidence: float = 0.95) -> WelchResult:
    """Two-sided Welch's t-test (unequal variances) with CI and effect sizes."""
    if a.size < 2 or b.size < 2:
        raise ValueError("each sample needs at least two values")
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    na, nb = int(a.size), int(b.size)
    se = math.sqrt(va / na + vb / nb)
    mean_a, mean_b = float(np.mean(a)), float(np.mean(b))
    diff = mean_b - mean_a
    if se == 0:
        if diff != 0:
            raise ValueError("zero variance in both samples: t-test undefined")
        t_stat, p, df = 0.0, 1.0, float(na + nb - 2)
    else:
        df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
        t_stat = (mean_a - mean_b) / se
        p = float(2.0 * stats.t.sf(abs(t_stat), df))
    t_crit = float(stats.t.ppf(0.5 + confidence / 2.0, df))
    sp = pooled_sd(a, b)
    d = diff / sp if sp > 0 else 0.0
    g = d * (1.0 - 3.0 / (4.0 * (na + nb) - 9.0))
    return WelchResult(
        t_statistic=t_stat,
        p_value=p,
        mean_a=mean_a,
        mean_b=mean_b,
        n_a=na,
        n_b=nb,
        sd_a=math.sqrt(va),
        sd_b=math.sqrt(vb),
        df=df,
        standard_error=se,
        mean_difference=diff,
        ci_low=diff - t_crit * se,
        ci_high=diff + t_crit * se,
        confidence=confidence,
        cohens_d=d,
        hedges_g=g,
    )


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm–Bonferroni step-down adjusted p-values (input order preserved).

    Sorted ascending ``p₍ᵢ₎``: ``p̃₍ᵢ₎ = max_{j≤i} min(1, (m − j + 1)·p₍ⱼ₎)``.
    """
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[idx]))
        adjusted[idx] = running
    return adjusted
