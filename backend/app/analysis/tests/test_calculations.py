"""Unit tests for the pure calculation functions (hand-checkable inputs)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import calculations as calc


def test_fit_line_recovers_exact_line_for_every_weighting() -> None:
    x = np.array([1.0, 2.0, 5.0, 10.0])
    y = 0.5 + 2.0 * x
    for w in ("none", "1/x", "1/x2"):
        fit = calc.fit_line(x, y, w)  # type: ignore[arg-type]
        assert fit.slope == pytest.approx(2.0)
        assert fit.intercept == pytest.approx(0.5)
        assert fit.r_squared == pytest.approx(1.0)


def test_weighting_shifts_fit_towards_low_levels() -> None:
    x = np.array([1.0, 10.0, 100.0])
    y = np.array([1.5, 10.0, 100.0])  # low point's response biased high
    plain = calc.fit_line(x, y, "none")
    weighted = calc.fit_line(x, y, "1/x2")
    # relative back-calculation error of the lowest calibrator (nominal x = 1)
    low_err_plain = abs(plain.predict_x(np.array([1.5]))[0] - 1.0)
    low_err_weighted = abs(weighted.predict_x(np.array([1.5]))[0] - 1.0)
    assert low_err_weighted < low_err_plain


def test_fit_line_input_validation() -> None:
    with pytest.raises(ValueError):
        calc.fit_line(np.array([1.0]), np.array([1.0]))
    with pytest.raises(ValueError):
        calc.fit_line(np.array([2.0, 2.0]), np.array([1.0, 3.0]))
    with pytest.raises(ValueError):
        calc.weights_for(np.array([0.0, 1.0]), "1/x")


def test_summary_stats() -> None:
    mean, sd, rsd = calc.summary_stats(np.array([90.0, 100.0, 110.0]))
    assert (mean, sd, rsd) == pytest.approx((100.0, 10.0, 10.0))
    assert calc.summary_stats(np.array([5.0]))[1] == 0.0
    with pytest.raises(ValueError):
        calc.summary_stats(np.array([]))


def _cal_frame() -> pd.DataFrame:
    # ratio = 0.01 * level exactly; IS area constant 1000
    levels = [5.0, 10.0, 20.0, 50.0]
    return pd.DataFrame(
        {
            "injection_id": [f"C{i}" for i in range(len(levels))],
            "level_ng_ml": levels,
            "analyte": ["a"] * len(levels),
            "analyte_area": [lv * 10.0 for lv in levels],
            "is_area": [1000.0] * len(levels),
        }
    )


def test_calibrate_back_calculation_is_exact_on_perfect_data() -> None:
    cal = calc.calibrate(_cal_frame(), "1/x")["a"]
    assert cal.fit.slope == pytest.approx(0.01)
    assert all(b.accuracy_pct == pytest.approx(100.0) for b in cal.back_calc)
    assert cal.max_abs_error_pct == pytest.approx(0.0, abs=1e-9)


def test_compute_recovery_with_unit_conversion() -> None:
    cal = calc.calibrate(_cal_frame(), "none")
    # extract 8 ng/mL (ratio 0.08) × 10 mL / 5 g = 16 ng/g measured; spiked 20 → 80 %
    frame = pd.DataFrame(
        {
            "injection_id": ["S1", "S2"],
            "sample_id": ["r1", "r2"],
            "analyte": ["a", "a"],
            "spike_ng_g": [20.0, 20.0],
            "analyte_area": [80.0, 90.0],
            "is_area": [1000.0, 1000.0],
        }
    )
    rows, groups = calc.compute_recovery(frame, cal, extraction_volume_ml=10, sample_mass_g=5)
    assert [r.recovery_pct for r in rows] == pytest.approx([80.0, 90.0])
    assert groups[0].mean_pct == pytest.approx(85.0) and groups[0].n == 2
    with pytest.raises(ValueError):
        calc.compute_recovery(frame, cal, extraction_volume_ml=0, sample_mass_g=5)
    with pytest.raises(ValueError, match="no calibration"):
        calc.compute_recovery(
            frame.assign(analyte="b"), cal, extraction_volume_ml=1, sample_mass_g=1
        )


def test_is_response_deduplicates_injections() -> None:
    cal = _cal_frame()  # mean IS 1000
    samples = pd.DataFrame(
        {
            "injection_id": ["S1", "S1", "S2"],
            "sample_id": ["a", "a", "b"],
            "is_area": [400, 400, 1000],
        }
    )
    ref, inj = calc.compute_is_response(cal, samples)
    assert ref == pytest.approx(1000.0)
    assert [i.response_pct for i in inj] == pytest.approx([40.0, 100.0])


def test_matrix_effect_slope_ratio() -> None:
    frame = pd.DataFrame(
        {
            "injection_id": list("abcd"),
            "curve": ["solvent", "solvent", "matrix", "matrix"],
            "level_ng_ml": [10.0, 20.0, 10.0, 20.0],
            "analyte": ["x"] * 4,
            "analyte_area": [100.0, 200.0, 75.0, 150.0],
        }
    )
    (me,) = calc.compute_matrix_effect(frame)
    assert me.matrix_effect_pct == pytest.approx(-25.0)
    with pytest.raises(ValueError, match="missing matrix"):
        calc.compute_matrix_effect(frame[frame["curve"] == "solvent"])


def test_welch_t_test() -> None:
    res = calc.welch_t_test(np.array([89.0, 90.0, 91.0]), np.array([60.0, 62.0, 64.0]))
    assert res.p_value < 0.01 and res.t_statistic > 0
    with pytest.raises(ValueError):
        calc.welch_t_test(np.array([1.0]), np.array([1.0, 2.0]))


# --------------------------------------------------------------------------
# Hand-calculated reference values (worked on paper, matched to 4+ decimals)
# --------------------------------------------------------------------------

# OLS example: x = 1..4, y = 2.1, 3.9, 6.2, 7.8
#   x̄ = 2.5, ȳ = 5.0, Sxx = 5, Sxy = 9.7  →  b = 1.94, a = 0.15
#   residuals 0.01, −0.13, 0.23, −0.11  →  SSres = 0.082, s_y/x = √(0.082/2) = 0.202485
#   SE(b) = s/√5 = 0.090554, SE(a) = s·√(1/4 + 2.5²/5) = 0.247992
#   SStot = 18.9 → R² = 1 − 0.082/18.9 = 0.995661
HAND_X = np.array([1.0, 2.0, 3.0, 4.0])
HAND_Y = np.array([2.1, 3.9, 6.2, 7.8])


def test_ols_matches_hand_calculation() -> None:
    fit = calc.fit_line(HAND_X, HAND_Y, "none")
    assert fit.slope == pytest.approx(1.94, abs=1e-10)
    assert fit.intercept == pytest.approx(0.15, abs=1e-10)
    assert fit.residual_sd == pytest.approx(0.202485, abs=1e-6)
    assert fit.se_slope == pytest.approx(0.090554, abs=1e-6)
    assert fit.se_intercept == pytest.approx(0.247992, abs=1e-6)
    assert fit.r_squared == pytest.approx(0.995661, abs=1e-6)
    assert fit.predict_y(np.array([2.0]))[0] == pytest.approx(4.03)


def test_weighted_1_over_x_matches_hand_calculation() -> None:
    # x = 1, 2, 4; y = 1, 3, 4; w = 1, 0.5, 0.25 (Σw = 1.75)
    # x̄_w = 3/1.75 = 12/7, ȳ_w = 3.5/1.75 = 2, Sxx_w = 13/7, Sxy_w = 2
    # → b = 14/13 = 1.076923, a = 2 − (14/13)(12/7) = 2/13 = 0.153846
    x, y = np.array([1.0, 2.0, 4.0]), np.array([1.0, 3.0, 4.0])
    fit = calc.fit_line(x, y, "1/x")
    assert fit.slope == pytest.approx(14 / 13, abs=1e-12)
    assert fit.intercept == pytest.approx(2 / 13, abs=1e-12)
    # Σw·r² = 4.5/13 → s = √(4.5/13) = 0.588348 (df = 1)
    assert fit.residual_sd == pytest.approx(0.588348, abs=1e-6)


def test_residuals_and_relative_error_hand_values() -> None:
    x, y = np.array([1.0, 2.0, 4.0]), np.array([1.0, 3.0, 4.0])
    cal = calc.calibrate_analyte("a", ["C1", "C2", "C3"], x, y, "1/x")
    first = cal.residuals[0]
    # ŷ(1) = 16/13 = 1.230769 → r = −0.230769; x̂ = (1 − 2/13)/(14/13) = 11/14
    assert first.predicted == pytest.approx(16 / 13)
    assert first.residual == pytest.approx(-3 / 13)
    assert first.back_calculated == pytest.approx(11 / 14)
    assert first.relative_error_pct == pytest.approx(-21.4286, abs=1e-4)
    # standardized = √1 · (−0.230769) / 0.588348 = −0.392232
    assert first.standardized == pytest.approx(-0.392232, abs=1e-6)
    assert [r.injection_id for r in cal.residuals] == ["C1", "C2", "C3"]
    # Σ|%RE| uses the level means: |11/14·100−100| + |x̂(2)| + |x̂(4)| deviations
    expected = sum(abs(r.relative_error_pct) for r in cal.residuals)
    assert cal.sum_abs_error_pct == pytest.approx(expected)


def test_two_point_fit_has_no_residual_sd() -> None:
    fit = calc.fit_line(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert fit.residual_sd is None and fit.se_slope is None and fit.se_intercept is None
    cal = calc.calibrate_analyte(
        "a", ["x", "y"], np.array([1.0, 2.0]), np.array([1.0, 2.0]), "none"
    )
    assert all(r.standardized is None for r in cal.residuals)


def test_heteroscedasticity_f_test_hand_values() -> None:
    # low replicates 1.0, 1.2, 0.8 → s² = 0.04; high 10, 12, 8 → s² = 4 → F = 100
    # F(0.99; 2, 2) = 99; for F(2, 2): P(F > f) = 1/(1 + f) = 1/101
    x = np.array([1.0, 1.0, 1.0, 10.0, 10.0, 10.0])
    y = np.array([1.0, 1.2, 0.8, 10.0, 12.0, 8.0])
    res = calc.heteroscedasticity_f_test(x, y, alpha=0.01)
    assert res is not None
    assert res.var_low == pytest.approx(0.04)
    assert res.var_high == pytest.approx(4.0)
    assert res.f_statistic == pytest.approx(100.0)
    assert res.f_critical == pytest.approx(99.0, abs=1e-6)
    assert res.p_value == pytest.approx(1 / 101, abs=1e-9)
    assert res.significant is True
    assert calc.heteroscedasticity_f_test(np.array([1.0, 2.0]), np.array([1.0, 2.0])) is None
    assert calc.heteroscedasticity_f_test(np.array([1.0, 1.0]), np.array([1.0, 2.0])) is None
    const = np.array([1.0, 1.0, 1.0, 10.0, 10.0])
    assert calc.heteroscedasticity_f_test(const, np.array([1.0, 1.0, 1.0, 9.0, 11.0])) is None


def test_detection_limits_hand_values() -> None:
    est = {e.method: e for e in calc.detection_limits(HAND_X, HAND_Y, k_lod=3, k_loq=10)}
    # residual SD: LOD = 3·0.2024846/1.94 = 0.3131205, LOQ = 10·0.2024846/1.94 = 1.043735
    assert est["residual_sd"].lod == pytest.approx(0.3131205, abs=1e-6)
    assert est["residual_sd"].loq == pytest.approx(1.043735, abs=1e-6)
    # intercept SD: LOD = 3·0.2479919/1.94 = 0.383493, LOQ = 10·0.2479919/1.94 = 1.278309
    assert est["intercept_sd"].lod == pytest.approx(0.383493, abs=1e-6)
    assert est["intercept_sd"].loq == pytest.approx(1.278309, abs=1e-6)
    assert "low_level_replicates" not in est  # single injection per level
    # ICH variant k = 3.3
    ich = calc.detection_limits(HAND_X, HAND_Y, k_lod=3.3, k_loq=10)[0]
    assert ich.lod == pytest.approx(0.344433, abs=1e-6)  # 3.3·0.2024846/1.94


def test_detection_limits_low_level_replicates() -> None:
    # lowest level replicates 0.09, 0.10, 0.11 → SD = 0.01; b = 0.1 → LOD 0.3, LOQ 1.0
    x = np.array([1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 10.0, 10.0, 10.0])
    y = np.array([0.09, 0.10, 0.11, 0.50, 0.49, 0.51, 1.0, 1.01, 0.99])
    estimates = calc.detection_limits(x, y, replicate_slope=0.1)
    rep = next(e for e in estimates if e.method == "low_level_replicates")
    assert rep.sigma == pytest.approx(0.01)
    assert (rep.lod, rep.loq) == pytest.approx((0.3, 1.0))
    assert rep.n == 3 and rep.max_level == 1.0
    assert calc.primary_limit(estimates).method == "low_level_replicates"
    two = calc.detection_limits(x[1:], y[1:], replicate_slope=0.1)
    assert calc.primary_limit(two).method == "residual_sd"
    only_rep = [e for e in estimates if e.method == "low_level_replicates"]
    assert calc.primary_limit(only_rep[:0] + only_rep, min_replicates=9).method == (
        "low_level_replicates"
    )
    with pytest.raises(ValueError):
        calc.primary_limit([])
    with pytest.raises(ValueError, match="positive"):
        calc.detection_limits(x, -y)


def test_low_range_mask() -> None:
    x = np.array([1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0])
    assert list(x[calc.low_range_mask(x, 10.0)]) == [1.0, 2.0, 5.0, 10.0]
    sparse = np.array([1.0, 100.0, 200.0, 400.0])
    assert list(sparse[calc.low_range_mask(sparse, 10.0)]) == [1.0, 100.0, 200.0]


def test_grubbs_critical_values_match_published_table() -> None:
    # two-sided α = 0.05 (ASTM E178 / Grubbs 1969 tables)
    table = {3: 1.155, 5: 1.715, 6: 1.887, 10: 2.290, 20: 2.709}
    for n, g in table.items():
        assert calc.grubbs_critical(n, 0.05) == pytest.approx(g, abs=1e-3)
    with pytest.raises(ValueError):
        calc.grubbs_critical(2)


def test_grubbs_test_hand_values() -> None:
    # mean 10.4, deviations 0.4 0.3 0.5 0.4 1.6; Σd² = 3.22 → s = √0.805 = 0.897218
    # G = 1.6/0.897218 = 1.783290 > 1.715 (n = 5)
    res = calc.grubbs_test(np.array([10.0, 10.1, 9.9, 10.0, 12.0]))
    assert res is not None
    assert res.g_statistic == pytest.approx(1.783290, abs=1e-6)
    assert res.is_outlier and res.suspect_index == 4 and res.suspect_value == 12.0
    clean = calc.grubbs_test(np.array([10.0, 10.1, 9.9]))  # G = 0.1/0.1 = 1.0 < 1.155
    assert clean is not None and clean.g_statistic == pytest.approx(1.0) and not clean.is_outlier
    assert calc.grubbs_test(np.array([1.0, 2.0])) is None
    assert calc.grubbs_test(np.array([5.0, 5.0, 5.0])) is None


def test_recovery_uncertainty_hand_values() -> None:
    # level 1: 90/100/110 → mean 100, RSD 10; level 2: 80/90/100 → mean 90, RSD 11.1111
    # u(Rw) = √((2·100 + 2·123.4568)/4) = 10.5702; RMS bias = √((0² + 10²)/2) = 7.0711
    # u_c = √(111.7284 + 50) = 12.7172; U = 2·u_c = 25.4345
    groups = [
        calc.RecoveryGroup("a", 10.0, 3, 100.0, 10.0, 10.0),
        calc.RecoveryGroup("a", 50.0, 3, 90.0, 10.0, 100.0 / 9.0),
        calc.RecoveryGroup("b", 10.0, 1, 50.0, 0.0, 0.0),
    ]
    u = calc.recovery_uncertainty("a", groups)
    assert u.u_rw_pct == pytest.approx(10.5702, abs=1e-4)
    assert u.rms_bias_pct == pytest.approx(7.0711, abs=1e-4)
    assert u.u_combined_pct == pytest.approx(12.7172, abs=1e-4)
    assert u.expanded_pct == pytest.approx(25.4345, abs=1e-4)
    with_ref = calc.recovery_uncertainty("a", groups, u_cref_pct=3.0, coverage_factor=3.0)
    assert with_ref.u_bias_pct == pytest.approx((50 + 9) ** 0.5, abs=1e-9)
    assert with_ref.coverage_factor == 3.0
    single = calc.recovery_uncertainty("b", groups)  # n = 1 → no precision term
    assert single.u_rw_pct == 0.0 and single.expanded_pct == pytest.approx(100.0)
    with pytest.raises(ValueError):
        calc.recovery_uncertainty("zzz", groups)


def test_welch_effect_size_hand_values() -> None:
    # a: mean 90, s² 1; b: mean 62, s² 4; n = 3 each
    # SE = √(1/3 + 4/3) = 1.290994; t = 28/SE = 21.688707
    # df = (5/3)² / ((1/3)²/2 + (4/3)²/2) = 50/17 = 2.941176
    # s_p = √((2·1 + 2·4)/4) = 1.581139; d = −28/s_p = −17.708754; g = d·(1 − 3/15) = −14.167003
    res = calc.welch_t_test(np.array([89.0, 90.0, 91.0]), np.array([60.0, 62.0, 64.0]))
    assert res.standard_error == pytest.approx(1.290994, abs=1e-6)
    assert res.t_statistic == pytest.approx(21.688707, abs=1e-6)
    assert res.df == pytest.approx(50 / 17, abs=1e-9)
    assert res.mean_difference == pytest.approx(-28.0)
    assert res.cohens_d == pytest.approx(-17.708754, abs=1e-6)
    assert res.hedges_g == pytest.approx(-14.167003, abs=1e-6)
    assert (res.sd_a, res.sd_b) == pytest.approx((1.0, 2.0))
    # same CI as SciPy's Welch interval (which is for a − b)
    from scipy import stats

    ref = stats.ttest_ind([89, 90, 91], [60, 62, 64], equal_var=False)
    ci = ref.confidence_interval(0.95)
    assert (res.ci_low, res.ci_high) == pytest.approx((-ci.high, -ci.low))
    assert res.p_value == pytest.approx(float(ref.pvalue))


def test_welch_zero_variance_edge_cases() -> None:
    same = calc.welch_t_test(np.array([5.0, 5.0]), np.array([5.0, 5.0]))
    assert same.p_value == 1.0 and same.t_statistic == 0.0 and same.cohens_d == 0.0
    with pytest.raises(ValueError, match="zero variance"):
        calc.welch_t_test(np.array([5.0, 5.0]), np.array([6.0, 6.0]))


def test_pooled_sd_hand_value() -> None:
    assert calc.pooled_sd(np.array([89.0, 90.0, 91.0]), np.array([60.0, 62.0, 64.0])) == (
        pytest.approx(2.5**0.5)
    )


def test_holm_adjustment_hand_values() -> None:
    # sorted 0.01·3 = 0.03, 0.03·2 = 0.06, 0.04·1 = 0.04 → monotone max → 0.06
    assert calc.holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert calc.holm_adjust([0.5, 0.6]) == pytest.approx([1.0, 1.0])
    assert calc.holm_adjust([]) == []


def _ion_frame(sample_ratio: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "injection_id": ["STD1", "STD2", "S1"],
            "sample_type": ["standard", "Standard", "sample"],
            "analyte": ["a", "a", "a"],
            "quantifier_area": [1000.0, 2000.0, 1000.0],
            "qualifier_area": [500.0, 1000.0, sample_ratio * 1000.0],
        }
    )


def test_ion_ratio_hand_values() -> None:
    (row,) = calc.compute_ion_ratios(_ion_frame(0.66))
    assert row.reference_ratio == pytest.approx(0.5)
    assert row.ion_ratio == pytest.approx(0.66)
    assert row.deviation_pct == pytest.approx(32.0)
    with pytest.raises(ValueError, match="missing columns"):
        calc.compute_ion_ratios(_ion_frame(0.5).drop(columns="sample_type"))
    no_std = _ion_frame(0.5).assign(sample_type="sample")
    with pytest.raises(ValueError, match="no standard"):
        calc.compute_ion_ratios(no_std)


def test_select_calibration_curve() -> None:
    base = _cal_frame()
    frame, used = calc.select_calibration_curve(base, "matrix-matched")
    assert used == "dataset" and len(frame) == len(base)
    both = pd.concat([base.assign(curve="solvent"), base.assign(curve="Matrix")])
    matrix, used = calc.select_calibration_curve(both, "matrix-matched")
    assert used == "matrix" and len(matrix) == len(base)
    solvent, used = calc.select_calibration_curve(both, "solvent")
    assert used == "solvent" and len(solvent) == len(base)
    with pytest.raises(ValueError, match="'matrix'"):
        calc.select_calibration_curve(base.assign(curve="solvent"), "matrix-matched")


def test_recovery_without_is_correction() -> None:
    cal = calc.calibrate(_cal_frame(), "none")
    cal_abs = calc.calibrate(_cal_frame(), "none", use_is=False)
    assert cal_abs["a"].fit.slope == pytest.approx(10.0)  # area = 10·level
    # IS suppressed to 50 %: ratio doubles; absolute area 80 → 8 ng/mL → 16 ng/g → 80 %
    frame = pd.DataFrame(
        {
            "injection_id": ["S1"],
            "sample_id": ["r1"],
            "analyte": ["a"],
            "spike_ng_g": [20.0],
            "analyte_area": [80.0],
            "is_area": [500.0],
        }
    )
    rows, _ = calc.compute_recovery(
        frame, cal, extraction_volume_ml=10, sample_mass_g=5, calibration_no_is=cal_abs
    )
    assert rows[0].recovery_pct == pytest.approx(160.0)
    assert rows[0].recovery_no_is_pct == pytest.approx(80.0)


def test_calibration_is_reference_lists_standards_in_order() -> None:
    ref, inj = calc.calibration_is_reference(_cal_frame())
    assert ref == pytest.approx(1000.0)
    assert [i.injection_id for i in inj] == ["C0", "C1", "C2", "C3"]
    assert inj[0].sample_id == "STD 5 ng/mL" and inj[0].response_pct == pytest.approx(100.0)
