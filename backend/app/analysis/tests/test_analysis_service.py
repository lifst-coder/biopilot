"""Analysis service on the seed scenario + idempotency and immutability."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.analysis import service
from app.analysis.models import AnalysisResult
from app.analysis.schemas import (
    AcceptanceCriteria,
    CalibrationOutput,
    CriteriaCreate,
    IonRatioOutput,
    ISResponseOutput,
    LimitsOutput,
    RecoveryOutput,
)
from app.core.errors import ImmutableRecordError
from app.eln import service as eln
from app.eln.schemas import ConditionBlock, DatasetCreate, ExperimentCreate


def test_seed_scenario_numbers_come_out_of_the_csvs(
    session: Session, seeded: dict[str, int]
) -> None:
    base = service.get_metrics(session, seeded["#018"])
    changed = service.get_metrics(session, seeded["#024"])
    assert base.recovery_mean_pct is not None and 85 <= base.recovery_mean_pct <= 93
    assert changed.recovery_mean_pct is not None and 58 <= changed.recovery_mean_pct <= 66
    assert changed.is_injections_flagged == 3 and changed.is_injections_total == 10
    assert not any(f.code == "recovery_out_of_range" for f in base.flags)
    failing = {f.analyte for f in changed.flags if f.code == "recovery_out_of_range"}
    assert failing == {"carbendazim", "thiabendazole"}


def test_matrix_effect_and_calibration_verification(
    session: Session, seeded: dict[str, int]
) -> None:
    me = service.get_metrics(session, seeded["#021"])
    assert me.matrix_effect_pct["imidacloprid"] < -20
    assert all(abs(v) <= 20 for k, v in me.matrix_effect_pct.items() if k != "imidacloprid")
    cal = service.latest_results(session, seeded["#023"])["calibration"].output
    assert isinstance(cal, CalibrationOutput)
    errors = {w.weighting: w.sum_abs_relative_error_pct for w in cal.weighting_comparison}
    assert errors["1/x"] < errors["none"] / 2


def test_run_is_idempotent_and_audited_once(session: Session, seeded: dict[str, int]) -> None:
    before = len(service.list_results(session, seeded["#018"]))
    again = service.run_experiment(session, seeded["#018"])
    assert again.created == 0 and again.reused == 4  # calibration, limits, recovery, IS
    assert len(service.list_results(session, seeded["#018"])) == before


def test_results_are_immutable(session: Session, seeded: dict[str, int]) -> None:
    rid = service.list_results(session, seeded["#018"])[0].id
    row = session.get(AnalysisResult, rid)
    assert row is not None
    row.output = {"tampered": True}
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_compare_detects_significant_drop(session: Session, seeded: dict[str, int]) -> None:
    cmp = service.compare(session, seeded["#018"], seeded["#024"])
    assert cmp.recovery_delta_pct_points is not None and cmp.recovery_delta_pct_points < -20
    assert cmp.recovery_t_test is not None and cmp.recovery_t_test.p_value < 0.001
    worst = min(cmp.per_analyte, key=lambda d: d.delta_pct_points)
    assert worst.analyte in {"carbendazim", "thiabendazole"}


def test_trend_covers_all_experiments(session: Session, seeded: dict[str, int]) -> None:
    trend = service.project_trend(session, seeded["project"])
    assert [t.code for t in trend] == [f"#0{n}" for n in range(18, 25)]
    no_recovery = {t.code for t in trend if t.recovery_mean_pct is None}
    assert no_recovery == {"#021", "#023"}


def test_recovery_without_calibration_is_skipped(session: Session, seeded: dict[str, int]) -> None:
    exp = eln.create_experiment(
        session,
        seeded["project"],
        ExperimentCreate(
            code="#900",
            title="no cal",
            performed_on=date(2026, 11, 1),
            raw_note="n",
            condition_block=ConditionBlock(sample_mass_g=10, extraction_volume_ml=10),
        ),
    )
    eln.create_dataset(
        session,
        exp.id,
        DatasetCreate(
            kind="recovery",
            filename="r.csv",
            content="injection_id,sample_id,analyte,spike_ng_g,analyte_area,is_area\nS,a,x,10,1,1\n",
        ),
    )
    res = service.run_experiment(session, exp.id)
    assert res.results == [] and "no calibration" in res.skipped[0]
    assert service.get_metrics(session, exp.id).analyzed is False


def test_calibration_output_includes_fit_line(session: Session, seeded: dict[str, int]) -> None:
    cal = service.latest_results(session, seeded["#018"])["calibration"].output
    assert isinstance(cal, CalibrationOutput)
    first = cal.analytes[0]
    assert [p.level for p in first.fit_line] == [b.level for b in first.back_calc]
    assert first.fit_line[0].response_ratio == pytest.approx(
        first.intercept + first.slope * first.fit_line[0].level
    )


# ----------------------------------------------------------- completion criteria


def test_every_seed_experiment_has_all_applicable_metrics(
    session: Session, seeded: dict[str, int]
) -> None:
    """Every metric is computed from the seed CSVs (calibration → limits, recovery → IS/U)."""
    for code in ("#018", "#019", "#020", "#022", "#023", "#024"):
        m = service.get_metrics(session, seeded[code])
        assert m.min_r_squared is not None and m.min_r_squared > 0.99, code
        assert len(m.limits) == 5 and all(0 < lim.lod < lim.loq for lim in m.limits), code
        assert m.qc_status in {"pass", "warning", "fail"}
        assert m.criteria_versions == ["default"]
        assert {v.analyte for v in m.qc_verdicts} == {lim.analyte for lim in m.limits}
        if code != "#023":
            assert m.recovery_rsd_pct is not None and m.recovery_rsd_pct > 0
            assert len(m.expanded_uncertainty_pct) == 5
            assert m.is_injections_total and m.is_injections_total >= 5
    me = service.get_metrics(session, seeded["#021"])
    assert me.limits == [] and len(me.matrix_effect_pct) == 5


def test_024_is_suppressed_injections_are_flagged(session: Session, seeded: dict[str, int]) -> None:
    latest = service.latest_results(session, seeded["#024"])
    isr = latest["is_response"]
    assert isinstance(isr.output, ISResponseOutput)
    suppressed = {f.context["injection_id"] for f in isr.flags if f.code == "is_suppression"}
    assert len(suppressed) == 3
    assert {i.injection_id for i in isr.output.injections if i.flagged} == suppressed
    assert all(i.response_pct < 50 for i in isr.output.injections if i.flagged)
    assert isr.output.calibration_injections and all(
        i.role == "calibration" for i in isr.output.calibration_injections
    )
    assert isr.output.reference_is_rsd_pct is not None and isr.output.reference_is_rsd_pct < 10
    # IS correction: suppressed injections recover far less without the IS ratio
    rec = latest["recovery"].output
    assert isinstance(rec, RecoveryOutput)
    for row in rec.rows:
        assert row.recovery_no_is_pct is not None
        if row.injection_id in suppressed:
            assert row.recovery_no_is_pct < row.recovery_pct * 0.6
    metrics = service.get_metrics(session, seeded["#024"])
    assert metrics.qc_status == "fail"
    failing = {v.analyte for v in metrics.qc_verdicts if v.status == "fail"}
    assert failing == {"carbendazim", "thiabendazole"}


def test_023_limits_and_heteroscedasticity_support_weighting(
    session: Session, seeded: dict[str, int]
) -> None:
    latest = service.latest_results(session, seeded["#023"])
    cal = latest["calibration"].output
    assert isinstance(cal, CalibrationOutput)
    # F-test (ANA-5): variance at 200 ng/mL ≫ 1 ng/mL for every analyte
    assert sorted(cal.heteroscedastic_analytes) == sorted(a.analyte for a in cal.analytes)
    for a in cal.analytes:
        assert a.heteroscedasticity is not None and a.heteroscedasticity.p_value < 0.01
        assert {f.weighting for f in a.fits} == {"none", "1/x", "1/x2"}
        by_w = {f.weighting: f for f in a.fits}
        assert by_w["1/x"].slope == a.slope and len(by_w["none"].residuals) == a.n
        assert len(a.residuals) == a.n == 24
    errors = {w.weighting: w.sum_abs_relative_error_pct for w in cal.weighting_comparison}
    assert errors["1/x"] < errors["none"] / 2
    lim = latest["limits"].output
    assert isinstance(lim, LimitsOutput)
    assert {a.primary_method for a in lim.analytes} == {"low_level_replicates"}
    for a in lim.analytes:
        assert a.lowest_level == 1.0 and a.lod_ng_g == pytest.approx(a.lod)  # 10 mL / 10 g
        assert {e.method for e in a.estimates} == {
            "residual_sd",
            "intercept_sd",
            "low_level_replicates",
        }


def test_compare_per_analyte_holm_and_effect_size(session: Session, seeded: dict[str, int]) -> None:
    cmp = service.compare(session, seeded["#018"], seeded["#024"])
    by = {d.analyte: d for d in cmp.per_analyte}
    for name in ("carbendazim", "thiabendazole"):
        d = by[name]
        assert d.p_holm is not None and d.p_value is not None and d.p_holm >= d.p_value
        assert d.significant is True and d.hedges_g is not None and d.hedges_g < -2
        assert d.ci_high is not None and d.ci_high < 0  # CI of (b − a) excludes 0
    assert set(cmp.significant_analytes) >= {"carbendazim", "thiabendazole"}
    t = cmp.recovery_t_test
    assert t is not None and t.mean_difference == pytest.approx(cmp.recovery_delta_pct_points)
    assert t.ci_low is not None and t.ci_high is not None and t.ci_low < t.ci_high < 0
    assert cmp.method is not None and cmp.method.version.startswith("comparison@")
    same = service.compare(session, seeded["#018"], seeded["#020"])
    assert not {"carbendazim", "thiabendazole"} <= set(same.significant_analytes)
    no_rec = service.compare(session, seeded["#021"], seeded["#023"])
    assert no_rec.per_analyte == [] and no_rec.recovery_t_test is None


def test_criteria_versions_keep_old_results_and_rerun_creates_new(
    session: Session, seeded: dict[str, int]
) -> None:
    exp = seeded["#024"]
    before = {r.id: r for r in service.list_results(session, exp)}
    v1 = service.create_criteria_version(
        session,
        seeded["project"],
        CriteriaCreate(criteria=AcceptanceCriteria(recovery_min_pct=40.0), note="relaxed"),
    )
    assert v1.version == 1 and v1.label == f"project-{seeded['project']}@v1"
    run = service.run_experiment(session, exp)
    assert run.created == 4 and run.reused == 0
    for r in service.list_results(session, exp):
        if r.id in before:
            assert r == before[r.id]  # stored results are untouched
    metrics = service.get_metrics(session, exp)
    assert metrics.criteria_versions == [v1.label]
    assert all(f.criteria_version == v1.label for f in metrics.flags)
    for f in metrics.flags:
        if f.code == "recovery_out_of_range":
            assert f.threshold_low == 40.0 and f.value < 40.0
    assert service.run_experiment(session, exp).created == 0
    history = service.get_project_criteria(session, seeded["project"]).history
    assert [h.version for h in history] == [0, 1]


def _experiment(session: Session, seeded: dict[str, int], code: str, **cond: object) -> int:
    exp = eln.create_experiment(
        session,
        seeded["project"],
        ExperimentCreate(
            code=code,
            title="t",
            performed_on=date(2026, 11, 2),
            raw_note="n",
            condition_block=ConditionBlock(sample_mass_g=10, extraction_volume_ml=10, **cond),
        ),
    )
    return exp.id


def _cal_csv(curves: dict[str, float]) -> str:
    lines = ["injection_id,level_ng_ml,analyte,analyte_area,is_area,curve"]
    i = 0
    for curve, slope in curves.items():
        for level in (1.0, 2.0, 5.0, 10.0, 20.0):
            i += 1
            lines.append(f"C{i},{level},x,{slope * level * 1000:.1f},1000,{curve}")
    return "\n".join(lines) + "\n"


def test_matrix_matched_calibration_selects_matrix_curve(
    session: Session, seeded: dict[str, int]
) -> None:
    content = _cal_csv({"solvent": 0.010, "matrix": 0.008})
    ids = {}
    for code, cal_type in (("#901", "matrix-matched"), ("#902", None)):
        extra = {"calibration_type": cal_type} if cal_type else {}
        ids[code] = _experiment(session, seeded, code, **extra)
        eln.create_dataset(
            session, ids[code], DatasetCreate(kind="calibration", filename="c.csv", content=content)
        )
        service.run_experiment(session, ids[code])
    mm = service.latest_results(session, ids["#901"])["calibration"]
    sv = service.latest_results(session, ids["#902"])["calibration"]
    assert isinstance(mm.output, CalibrationOutput) and isinstance(sv.output, CalibrationOutput)
    assert mm.output.curve_used == "matrix" and mm.output.calibration_type == "matrix-matched"
    assert mm.output.analytes[0].slope == pytest.approx(0.008)
    assert sv.output.curve_used == "solvent" and sv.output.analytes[0].slope == pytest.approx(0.010)
    assert mm.parameters["calibration_type"] == "matrix-matched"
    assert mm.input_fingerprint != sv.input_fingerprint  # same dataset, different parameter


def test_data_problems_are_reported_as_skipped(session: Session, seeded: dict[str, int]) -> None:
    exp_id = _experiment(session, seeded, "#903", calibration_type="matrix-matched")
    solvent_only = _cal_csv({"solvent": 0.01})
    eln.create_dataset(
        session, exp_id, DatasetCreate(kind="calibration", filename="c.csv", content=solvent_only)
    )
    eln.create_dataset(
        session,
        exp_id,
        DatasetCreate(
            kind="matrix_effect",
            filename="m.csv",
            content="injection_id,curve,level_ng_ml,analyte,analyte_area\nA,solvent,1,x,10\n",
        ),
    )
    res = service.run_experiment(session, exp_id)
    assert res.results == []
    assert any(s.startswith("calibration:") for s in res.skipped)
    assert any(s.startswith("matrix_effect:") for s in res.skipped)


def test_ion_ratio_from_other_dataset_with_ion_columns(
    session: Session, seeded: dict[str, int]
) -> None:
    exp_id = _experiment(session, seeded, "#904")
    content = (
        "injection_id,sample_type,analyte,quantifier_area,qualifier_area\n"
        "STD-1,standard,x,1000,500\nSTD-2,standard,x,2000,1000\n"
        "S-1,sample,x,1000,550\nS-2,sample,x,1000,700\n"
    )
    eln.create_dataset(
        session, exp_id, DatasetCreate(kind="other", filename="ion.csv", content=content)
    )
    eln.create_dataset(
        session, exp_id, DatasetCreate(kind="other", filename="note.csv", content="a,b\n1,2\n")
    )
    res = service.run_experiment(session, exp_id)
    (ion,) = res.results
    assert isinstance(ion.output, IonRatioOutput)
    assert [round(r.deviation_pct, 6) for r in ion.output.rows] == [10.0, 40.0]
    assert ion.output.flagged_count == 1 and ion.flags[0].context["injection_id"] == "S-2"
    m = service.get_metrics(session, exp_id)
    assert m.ion_ratio_injections_flagged == 1 and m.qc_status == "fail"
    bad = _experiment(session, seeded, "#905")
    eln.create_dataset(
        session,
        bad,
        DatasetCreate(kind="other", filename="i.csv", content=content.replace("standard", "x")),
    )
    assert service.run_experiment(session, bad).skipped[0].startswith("ion_ratio:")


def test_report_renders_stored_values(session: Session, seeded: dict[str, int]) -> None:
    text, media, name = service.build_report(session, seeded["#024"], "markdown")
    assert media == "text/markdown" and name == "biopilot-024-analysis.md"
    rec = service.latest_results(session, seeded["#024"])["recovery"].output
    assert isinstance(rec, RecoveryOutput)
    assert f"{rec.overall_mean_pct:.1f}" in text
    assert "is_suppression" in text and "Σ\\|%RE\\|" in text
    csv_text, media, name = service.build_report(session, seeded["#021"], "csv")
    assert media == "text/csv" and name.endswith(".csv")
    assert "matrix_effect," in csv_text and "imidacloprid" in csv_text
    md21, _, _ = service.build_report(session, seeded["#021"], "markdown")
    assert "ME %" in md21
    md23, _, _ = service.build_report(session, seeded["#023"], "markdown")
    assert "low_level_replicates" in md23
    assert service.list_methods()[0].kind == "calibration"
