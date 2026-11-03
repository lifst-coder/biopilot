"""Analysis service: runs deterministic calculations and stores immutable results.

Depends only on :mod:`app.eln.service` (to read datasets). Never interprets results.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import numpy as np
import pandas as pd
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import calculations as calc
from app.analysis.criteria import (
    DEFAULT_CRITERIA,
    calibration_flags,
    is_response_flag,
    matrix_effect_flag,
    recovery_flags,
)
from app.analysis.models import AnalysisResult
from app.analysis.schemas import (
    AcceptanceCriteria,
    AnalysisOutput,
    AnalysisResultOut,
    AnalyteCalibrationOut,
    AnalyteDelta,
    AnalyteRecoverySummary,
    BackCalcLevelOut,
    CalibrationOutput,
    CalibrationPoint,
    ExperimentMetrics,
    ISInjectionOut,
    ISResponseOutput,
    MatrixEffectOut,
    MatrixEffectOutput,
    MetricsComparison,
    QCFlag,
    RecoveryGroupOut,
    RecoveryOutput,
    RecoveryRowOut,
    RecoveryTTest,
    ResultKind,
    RunResponse,
    TrendPoint,
    WeightingComparison,
)
from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import DatasetOut

METHOD_VERSIONS: dict[ResultKind, str] = {
    "calibration": "calibration@2",
    "recovery": "recovery@1",
    "is_response": "is_response@1",
    "matrix_effect": "matrix_effect@1",
}

_OUTPUT_ADAPTER: TypeAdapter[AnalysisOutput] = TypeAdapter(AnalysisOutput)


def get_criteria() -> AcceptanceCriteria:
    """Active acceptance criteria (static defaults for now)."""
    return DEFAULT_CRITERIA


# ------------------------------------------------------------ persistence


def _to_out(row: AnalysisResult) -> AnalysisResultOut:
    return AnalysisResultOut(
        id=row.id,
        experiment_id=row.experiment_id,
        kind=row.kind,
        method_version=row.method_version,
        input_dataset_ids=row.input_dataset_ids,
        input_fingerprint=row.input_fingerprint,
        parameters=row.parameters,
        output=_OUTPUT_ADAPTER.validate_python(row.output),
        flags=[QCFlag.model_validate(f) for f in row.flags],
        created_at=row.created_at,
    )


def _fingerprint(kind: ResultKind, datasets: list[DatasetOut], params: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "method": METHOD_VERSIONS[kind],
            "datasets": [d.sha256 for d in datasets],
            "params": params,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _store(
    session: Session,
    *,
    experiment_id: int,
    project_id: int,
    kind: ResultKind,
    datasets: list[DatasetOut],
    params: dict[str, Any],
    output: AnalysisOutput,
    flags: list[QCFlag],
    actor: Actor,
) -> tuple[AnalysisResultOut, bool]:
    """Persist a result unless an identical-input one exists. Returns ``(result, created)``."""
    fingerprint = _fingerprint(kind, datasets, params)
    existing = session.scalar(
        select(AnalysisResult).where(
            AnalysisResult.experiment_id == experiment_id,
            AnalysisResult.input_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return _to_out(existing), False
    row = AnalysisResult(
        experiment_id=experiment_id,
        kind=kind,
        method_version=METHOD_VERSIONS[kind],
        input_dataset_ids=[d.id for d in datasets],
        input_fingerprint=fingerprint,
        parameters=params,
        output=output.model_dump(mode="json"),
        flags=[f.model_dump(mode="json") for f in flags],
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="analysis.run",
        entity_type="analysis.AnalysisResult",
        entity_id=row.id,
        project_id=project_id,
        payload={"experiment_id": experiment_id, "kind": kind, "fingerprint": fingerprint},
    )
    return _to_out(row), True


def _frame(session: Session, dataset: DatasetOut) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(eln.get_dataset_content(session, dataset.id)))


# ------------------------------------------------------------ computations


def _calibration_output(
    frame: pd.DataFrame, weighting: calc.Weighting, c: AcceptanceCriteria
) -> tuple[CalibrationOutput, list[QCFlag], dict[str, calc.AnalyteCalibration]]:
    cal = calc.calibrate(frame, weighting)
    analytes: list[AnalyteCalibrationOut] = []
    flags: list[QCFlag] = []
    for name, item in cal.items():
        group = frame[frame["analyte"] == name]
        points = [
            CalibrationPoint(level=float(lv), response_ratio=float(r))
            for lv, r in zip(group["level_ng_ml"], calc.response_ratio(group), strict=True)
        ]
        analytes.append(
            AnalyteCalibrationOut(
                analyte=name,
                slope=item.fit.slope,
                intercept=item.fit.intercept,
                r_squared=item.fit.r_squared,
                n=item.fit.n,
                weighting=weighting,
                max_abs_back_calc_error_pct=item.max_abs_error_pct,
                back_calc=[BackCalcLevelOut(**b.__dict__) for b in item.back_calc],
                points=points,
                fit_line=[
                    CalibrationPoint(
                        level=b.level, response_ratio=item.fit.intercept + item.fit.slope * b.level
                    )
                    for b in item.back_calc
                ],
            )
        )
        flags += calibration_flags(name, item.fit.r_squared, item.max_abs_error_pct, c)
    comparison = [
        WeightingComparison(
            weighting=w, sum_abs_relative_error_pct=calc.weighting_error_sum(frame, w)
        )
        for w in ("none", "1/x", "1/x2")
    ]
    return (
        CalibrationOutput(weighting=weighting, analytes=analytes, weighting_comparison=comparison),
        flags,
        cal,
    )


def _recovery_output(
    frame: pd.DataFrame,
    cal: dict[str, calc.AnalyteCalibration],
    volume: float,
    mass: float,
    c: AcceptanceCriteria,
) -> tuple[RecoveryOutput, list[QCFlag]]:
    rows, groups = calc.compute_recovery(
        frame, cal, extraction_volume_ml=volume, sample_mass_g=mass
    )
    all_values = np.array([r.recovery_pct for r in rows])
    mean, _sd, rsd = calc.summary_stats(all_values)
    flags: list[QCFlag] = []
    for g in groups:
        flags += recovery_flags(g.analyte, g.spike_ng_g, g.mean_pct, g.rsd_pct, c)
    return (
        RecoveryOutput(
            overall_mean_pct=mean,
            overall_rsd_pct=rsd,
            n=len(rows),
            groups=[RecoveryGroupOut(**g.__dict__) for g in groups],
            rows=[RecoveryRowOut(**r.__dict__) for r in rows],
        ),
        flags,
    )


def _is_output(
    cal_frame: pd.DataFrame, sample_frame: pd.DataFrame, c: AcceptanceCriteria
) -> tuple[ISResponseOutput, list[QCFlag]]:
    reference, injections = calc.compute_is_response(cal_frame, sample_frame)
    flags: list[QCFlag] = []
    out: list[ISInjectionOut] = []
    for inj in injections:
        flag = is_response_flag(inj.injection_id, inj.sample_id, inj.response_pct, c)
        if flag is not None:
            flags.append(flag)
        out.append(ISInjectionOut(**inj.__dict__, flagged=flag is not None))
    return (
        ISResponseOutput(reference_is_area=reference, injections=out, flagged_count=len(flags)),
        flags,
    )


def _matrix_output(
    frame: pd.DataFrame, c: AcceptanceCriteria
) -> tuple[MatrixEffectOutput, list[QCFlag]]:
    effects = calc.compute_matrix_effect(frame)
    flags = [f for e in effects if (f := matrix_effect_flag(e.analyte, e.matrix_effect_pct, c))]
    return MatrixEffectOutput(analytes=[MatrixEffectOut(**e.__dict__) for e in effects]), flags


def run_experiment(session: Session, experiment_id: int, *, actor: Actor = "user") -> RunResponse:
    """Run every applicable analysis for an experiment's latest dataset of each kind."""
    exp = eln.get_experiment(session, experiment_id)
    criteria = get_criteria()
    latest: dict[str, DatasetOut] = {}
    for ds in eln.list_datasets(session, experiment_id):
        latest[ds.kind] = ds  # later uploads supersede earlier ones of the same kind
    cond = exp.condition_block
    weighting: calc.Weighting = cond.calibration_weighting or "none"
    results: list[AnalysisResultOut] = []
    skipped: list[str] = []
    created = 0

    def store(
        kind: ResultKind,
        datasets: list[DatasetOut],
        params: dict[str, Any],
        output: AnalysisOutput,
        flags: list[QCFlag],
    ) -> None:
        nonlocal created
        result, is_new = _store(
            session,
            experiment_id=experiment_id,
            project_id=exp.project_id,
            kind=kind,
            datasets=datasets,
            params=params,
            output=output,
            flags=flags,
            actor=actor,
        )
        results.append(result)
        created += int(is_new)

    cal_ds = latest.get("calibration")
    cal_frame: pd.DataFrame | None = None
    cal_map: dict[str, calc.AnalyteCalibration] | None = None
    if cal_ds is not None:
        cal_frame = _frame(session, cal_ds)
        cal_out, cal_flags, cal_map = _calibration_output(cal_frame, weighting, criteria)
        store("calibration", [cal_ds], {"weighting": weighting}, cal_out, cal_flags)

    rec_ds = latest.get("recovery")
    if rec_ds is not None:
        if cal_ds is None or cal_map is None or cal_frame is None:
            skipped.append("recovery: experiment has no calibration dataset")
        elif cond.extraction_volume_ml is None or cond.sample_mass_g is None:
            skipped.append("recovery: condition block lacks extraction_volume_ml/sample_mass_g")
        else:
            rec_frame = _frame(session, rec_ds)
            params = {
                "weighting": weighting,
                "extraction_volume_ml": cond.extraction_volume_ml,
                "sample_mass_g": cond.sample_mass_g,
            }
            rec_out, rec_flags = _recovery_output(
                rec_frame, cal_map, cond.extraction_volume_ml, cond.sample_mass_g, criteria
            )
            store("recovery", [cal_ds, rec_ds], params, rec_out, rec_flags)
            is_out, is_flags = _is_output(cal_frame, rec_frame, criteria)
            store("is_response", [cal_ds, rec_ds], {}, is_out, is_flags)

    me_ds = latest.get("matrix_effect")
    if me_ds is not None:
        me_out, me_flags = _matrix_output(_frame(session, me_ds), criteria)
        store("matrix_effect", [me_ds], {}, me_out, me_flags)
    if not latest:
        skipped.append("experiment has no datasets")
    return RunResponse(
        experiment_id=experiment_id,
        results=results,
        created=created,
        reused=len(results) - created,
        skipped=skipped,
    )


# ----------------------------------------------------------------- queries


def get_result(session: Session, result_id: int) -> AnalysisResultOut:
    row = session.get(AnalysisResult, result_id)
    if row is None:
        raise NotFoundError(f"AnalysisResult {result_id} not found")
    return _to_out(row)


def list_results(
    session: Session, experiment_id: int | None = None, kind: ResultKind | None = None
) -> list[AnalysisResultOut]:
    stmt = select(AnalysisResult).order_by(AnalysisResult.id)
    if experiment_id is not None:
        stmt = stmt.where(AnalysisResult.experiment_id == experiment_id)
    if kind is not None:
        stmt = stmt.where(AnalysisResult.kind == kind)
    return [_to_out(r) for r in session.scalars(stmt)]


def latest_results(session: Session, experiment_id: int) -> dict[ResultKind, AnalysisResultOut]:
    """Most recent result of each kind for an experiment."""
    ids = session.scalars(
        select(func.max(AnalysisResult.id))
        .where(AnalysisResult.experiment_id == experiment_id)
        .group_by(AnalysisResult.kind)
    ).all()
    out: dict[ResultKind, AnalysisResultOut] = {}
    for rid in ids:
        res = get_result(session, rid)
        out[res.kind] = res
    return out


def get_metrics(session: Session, experiment_id: int) -> ExperimentMetrics:
    """Headline metrics assembled from the latest stored results (no recomputation)."""
    eln.get_experiment(session, experiment_id)
    latest = latest_results(session, experiment_id)
    if not latest:
        return ExperimentMetrics(experiment_id=experiment_id, analyzed=False)
    m = ExperimentMetrics(
        experiment_id=experiment_id,
        analyzed=True,
        source_result_ids=sorted(r.id for r in latest.values()),
        flags=[f for r in latest.values() for f in r.flags],
    )
    if (rec := latest.get("recovery")) and isinstance(rec.output, RecoveryOutput):
        m.recovery_mean_pct = rec.output.overall_mean_pct
        m.recovery_rsd_pct = rec.output.overall_rsd_pct
        m.recovery_n = rec.output.n
        for analyte in sorted({r.analyte for r in rec.output.rows}):
            vals = np.array([r.recovery_pct for r in rec.output.rows if r.analyte == analyte])
            mean, _sd, rsd = calc.summary_stats(vals)
            m.per_analyte_recovery.append(
                AnalyteRecoverySummary(analyte=analyte, mean_pct=mean, rsd_pct=rsd, n=vals.size)
            )
    if (cal := latest.get("calibration")) and isinstance(cal.output, CalibrationOutput):
        m.min_r_squared = min(a.r_squared for a in cal.output.analytes)
        m.max_abs_back_calc_error_pct = max(
            a.max_abs_back_calc_error_pct for a in cal.output.analytes
        )
        m.calibration_weighting = cal.output.weighting
    if (isr := latest.get("is_response")) and isinstance(isr.output, ISResponseOutput):
        m.is_injections_total = len(isr.output.injections)
        m.is_injections_flagged = isr.output.flagged_count
    if (me := latest.get("matrix_effect")) and isinstance(me.output, MatrixEffectOutput):
        m.matrix_effect_pct = {a.analyte: a.matrix_effect_pct for a in me.output.analytes}
    return m


def _recovery_values(session: Session, experiment_id: int) -> dict[str, list[float]]:
    rec = latest_results(session, experiment_id).get("recovery")
    if rec is None or not isinstance(rec.output, RecoveryOutput):
        return {}
    values: dict[str, list[float]] = {}
    for r in rec.output.rows:
        values.setdefault(r.analyte, []).append(r.recovery_pct)
    return values


def compare(session: Session, a: int, b: int) -> MetricsComparison:
    """Numerical comparison of experiment ``b`` against ``a`` (Welch t-test on recoveries)."""
    ma, mb = get_metrics(session, a), get_metrics(session, b)
    va, vb = _recovery_values(session, a), _recovery_values(session, b)
    per_analyte = [
        AnalyteDelta(
            analyte=name,
            mean_a_pct=float(np.mean(va[name])),
            mean_b_pct=float(np.mean(vb[name])),
            delta_pct_points=float(np.mean(vb[name]) - np.mean(va[name])),
        )
        for name in sorted(set(va) & set(vb))
    ]
    t_test: RecoveryTTest | None = None
    flat_a = np.array([v for vs in va.values() for v in vs])
    flat_b = np.array([v for vs in vb.values() for v in vs])
    if flat_a.size >= 2 and flat_b.size >= 2:
        w = calc.welch_t_test(flat_a, flat_b)
        t_test = RecoveryTTest(t_statistic=w.t_statistic, p_value=w.p_value, n_a=w.n_a, n_b=w.n_b)
    delta = (
        mb.recovery_mean_pct - ma.recovery_mean_pct
        if ma.recovery_mean_pct is not None and mb.recovery_mean_pct is not None
        else None
    )
    return MetricsComparison(
        experiment_a=a,
        experiment_b=b,
        metrics_a=ma,
        metrics_b=mb,
        recovery_delta_pct_points=delta,
        per_analyte=per_analyte,
        recovery_t_test=t_test,
    )


def project_trend(session: Session, project_id: int) -> list[TrendPoint]:
    """Recovery trend across a project's experiments (chronological)."""
    points: list[TrendPoint] = []
    for exp in eln.list_experiments(session, project_id):
        m = get_metrics(session, exp.id)
        points.append(
            TrendPoint(
                experiment_id=exp.id,
                code=exp.code,
                performed_on=exp.performed_on.isoformat(),
                recovery_mean_pct=m.recovery_mean_pct,
                recovery_rsd_pct=m.recovery_rsd_pct,
                flag_count=len(m.flags),
                source_result_ids=m.source_result_ids,
            )
        )
    return points
