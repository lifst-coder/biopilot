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
