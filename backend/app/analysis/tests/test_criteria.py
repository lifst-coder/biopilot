"""QC flag rules against configurable criteria (boundary values are inclusive)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analysis import criteria as qc
from app.analysis.schemas import AcceptanceCriteria, QCFlag

C = AcceptanceCriteria()


def test_recovery_flags_boundaries() -> None:
    assert qc.recovery_flags("a", 10, 70.0, 20.0, C) == []
    assert qc.recovery_flags("a", 10, 120.0, 5.0, C) == []
    (low,) = qc.recovery_flags("a", 10, 69.9, 5.0, C, "v1")
    assert low.code == "recovery_out_of_range" and low.severity == "critical"
    assert low.criteria_version == "v1" and low.context == {"spike_ng_g": 10}
    codes = [f.code for f in qc.recovery_flags("a", 10, 121.0, 20.1, C)]
    assert codes == ["recovery_out_of_range", "recovery_rsd_high"]
    strict = AcceptanceCriteria(recovery_min_pct=80, rsd_max_pct=5)
    assert [f.code for f in qc.recovery_flags("a", 10, 75.0, 6.0, strict)] == [
        "recovery_out_of_range",
        "recovery_rsd_high",
    ]


def test_calibration_flags() -> None:
    assert qc.calibration_flags("a", 0.99, 20.0, C) == []
    codes = [f.code for f in qc.calibration_flags("a", 0.98, 25.0, C)]
    assert codes == ["calibration_r2_low", "calibration_back_calc_error"]


def test_is_response_flag_direction() -> None:
    assert qc.is_response_flag("S1", "x", 50.0, C) is None
    assert qc.is_response_flag("S1", "x", 150.0, C) is None
    sup = qc.is_response_flag("S1", "x", 43.0, C)
    enh = qc.is_response_flag("S2", "y", 151.0, C)
    assert sup is not None and sup.code == "is_suppression"
    assert sup.context == {"injection_id": "S1", "sample_id": "x"}
    assert enh is not None and enh.code == "is_enhancement"


def test_matrix_uncertainty_ion_ratio_and_loq_flags() -> None:
    assert qc.matrix_effect_flag("a", -20.0, C) is None
    me = qc.matrix_effect_flag("a", -29.0, C)
    assert me is not None and me.threshold_low == -20 and me.threshold_high == 20
    assert qc.uncertainty_flag("a", 50.0, C) is None
    u = qc.uncertainty_flag("a", 57.4, C)
    assert u is not None and u.code == "uncertainty_high" and u.context["coverage_factor"] == 2
    assert qc.ion_ratio_flag("a", "S1", 30.0, C) is None  # boundary inclusive
    ion = qc.ion_ratio_flag("a", "S1", -32.0, C)
    assert ion is not None and ion.severity == "critical"
    assert qc.loq_flag("a", 2.0, 2.0) is None
    loq = qc.loq_flag("a", 2.5, 2.0)
    assert loq is not None and loq.severity == "info"
    out = qc.outlier_flag("a", 10.0, "S-03", 1.9, 1.715, 0.05, "default")
    assert out.code == "outlier_suspected" and out.context["injection_id"] == "S-03"


def _flag(code: str, severity: str, analyte: str | None) -> QCFlag:
    return QCFlag(code=code, severity=severity, analyte=analyte, value=1.0)  # type: ignore[arg-type]


def test_verdicts_and_overall_status() -> None:
    flags = [
        _flag("recovery_out_of_range", "critical", "a"),
        _flag("uncertainty_high", "warning", "a"),
        _flag("outlier_suspected", "warning", "b"),
        _flag("loq_above_lowest_level", "info", "c"),
        _flag("is_suppression", "warning", None),
    ]
    by = {v.analyte: v for v in qc.verdicts(["a", "b", "c", "a"], flags)}
    assert by["a"].status == "fail" and by["a"].failed_checks == ["recovery_out_of_range"]
    assert by["a"].warning_checks == ["uncertainty_high"]
    assert by["b"].status == "warning"
    assert by["c"].status == "pass"
    assert qc.overall_status(flags) == "fail"
    assert qc.overall_status(flags[2:]) == "warning"
    assert qc.overall_status(flags[3:4]) == "pass"
    assert qc.overall_status([]) == "pass"


@pytest.mark.parametrize(
    "bad",
    [
        {"recovery_min_pct": 120, "recovery_max_pct": 70},
        {"is_response_min_pct": 150, "is_response_max_pct": 50},
        {"lod_k": 10, "loq_k": 3},
        {"r_squared_min": 1.5},
        {"grubbs_alpha": 0},
    ],
)
def test_invalid_criteria_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        AcceptanceCriteria(**bad)
