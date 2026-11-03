"""Analysis service on the seed scenario + idempotency and immutability."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.analysis import service
from app.analysis.models import AnalysisResult
from app.analysis.schemas import CalibrationOutput
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
    assert again.created == 0 and again.reused == 3
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
