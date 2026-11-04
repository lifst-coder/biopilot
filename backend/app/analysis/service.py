"""Analysis service: runs deterministic calculations and stores immutable results.

Depends only on :mod:`app.eln.service` (to read datasets). Never interprets results.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any, cast

import numpy as np
import pandas as pd
from pydantic import TypeAdapter
from sqlalchemy import Text, func, select, type_coerce
from sqlalchemy.orm import Session

from app.analysis import calculations as calc
from app.analysis.criteria import (
    DEFAULT_CRITERIA,
    DEFAULT_CRITERIA_LABEL,
    calibration_flags,
    calibration_type_flag,
    ion_ratio_flag,
    is_response_flag,
    loq_flag,
    matrix_effect_flag,
    outlier_flag,
    overall_status,
    recovery_flags,
    uncertainty_flag,
    verdicts,
)
from app.analysis.methods import (
    METHOD_VERSIONS,
    all_method_docs,
    comparison_doc,
    method_doc,
)
from app.analysis.metrics_view import (
    OUTPUT_VIEW,
    CalibrationView,
    IonRatioView,
    ISResponseView,
    LimitsView,
    MatrixEffectView,
    RecoveryView,
    ResultView,
)
from app.analysis.models import AnalysisCriteriaVersion, AnalysisResult
from app.analysis.report import render_csv, render_markdown
from app.analysis.schemas import (
    SUPPORTED_CALIBRATION_TYPES,
    AcceptanceCriteria,
    AnalysisOutput,
    AnalysisResultOut,
    AnalyteCalibrationOut,
    AnalyteDelta,
    AnalyteLimitsOut,
    AnalyteLimitsSummary,
    AnalyteRecoverySummary,
    BackCalcLevelOut,
    CalibrationFitOut,
    CalibrationOutput,
    CalibrationPoint,
    CriteriaCreate,
    CriteriaVersionOut,
    ExperimentMetrics,
    GrubbsOut,
    HeteroscedasticityOut,
    IonRatioOutput,
    IonRatioRowOut,
    ISInjectionOut,
    ISResponseOutput,
    LimitEstimateOut,
    LimitsOutput,
    MatrixEffectOut,
    MatrixEffectOutput,
    MethodDoc,
    MetricsComparison,
    ProjectCriteria,
    QCFlag,
    RecoveryGroupOut,
    RecoveryOutput,
    RecoveryRowOut,
    RecoveryTTest,
    ReportFormat,
    ResidualOut,
    ResultHead,
    ResultKind,
    RunResponse,
    TrendPoint,
    UncertaintyOut,
    WeightingComparison,
)
from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import DATASET_NUMERIC_COLUMNS, ConditionBlock, DatasetOut

__all__ = ["METHOD_VERSIONS"]  # re-exported: CLAUDE.md refers to service.METHOD_VERSIONS

_OUTPUT_ADAPTER: TypeAdapter[AnalysisOutput] = TypeAdapter(AnalysisOutput)


# ------------------------------------------------------------ criteria (ANA-6)


def get_criteria() -> AcceptanceCriteria:
    """Built-in default acceptance criteria (SANTE/11312/2021)."""
    return DEFAULT_CRITERIA


def _criteria_label(project_id: int, version: int) -> str:
    return DEFAULT_CRITERIA_LABEL if version == 0 else f"project-{project_id}@v{version}"


def _default_version(project_id: int) -> CriteriaVersionOut:
    return CriteriaVersionOut(
        id=None,
        project_id=project_id,
        version=0,
        label=DEFAULT_CRITERIA_LABEL,
        criteria=DEFAULT_CRITERIA,
        note="기본값 (SANTE/11312/2021)",
    )


def _version_out(row: AnalysisCriteriaVersion) -> CriteriaVersionOut:
    return CriteriaVersionOut(
        id=row.id,
        project_id=row.project_id,
        version=row.version,
        label=_criteria_label(row.project_id, row.version),
        criteria=AcceptanceCriteria.model_validate(row.criteria),
        note=row.note,
        created_at=row.created_at,
    )


def get_project_criteria(session: Session, project_id: int) -> ProjectCriteria:
    """Active criteria version of a project (version 0 = defaults) and its history."""
    eln.get_project(session, project_id)
    rows = session.scalars(
        select(AnalysisCriteriaVersion)
        .where(AnalysisCriteriaVersion.project_id == project_id)
        .order_by(AnalysisCriteriaVersion.version)
    ).all()
    history = [_default_version(project_id)] + [_version_out(r) for r in rows]
    return ProjectCriteria(project_id=project_id, active=history[-1], history=history)


def create_criteria_version(
    session: Session, project_id: int, data: CriteriaCreate, *, actor: Actor = "user"
) -> CriteriaVersionOut:
    """Append a new immutable criteria version; existing results are left untouched."""
    current = get_project_criteria(session, project_id).active
    row = AnalysisCriteriaVersion(
        project_id=project_id,
        version=current.version + 1,
        criteria=data.criteria.model_dump(mode="json"),
        note=data.note,
    )
    session.add(row)
    session.flush()
    out = _version_out(row)
    record_event(
        session,
        actor=actor,
        action="analysis.criteria.create",
        entity_type="analysis.AnalysisCriteriaVersion",
        entity_id=row.id,
        project_id=project_id,
        payload={
            "version": row.version,
            "label": out.label,
            "previous_label": current.label,
            "changed": {
                k: [current.criteria.model_dump().get(k), v]
                for k, v in data.criteria.model_dump().items()
                if current.criteria.model_dump().get(k) != v
            },
        },
    )
    return out


def _criteria_params(version: CriteriaVersionOut) -> dict[str, str]:
    digest = hashlib.sha256(
        json.dumps(version.criteria.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    return {"criteria_version": version.label, "criteria_sha256": digest[:16]}


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
    """sha256 over method version + input dataset hashes + every parameter."""
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


def _frame(session: Session, dataset: DatasetOut, *, check: bool = True) -> pd.DataFrame:
    """The stored CSV of ``dataset`` as a frame.

    With ``check`` (default) every contract numeric column must hold finite numbers:
    an empty cell, ``nan`` or ``inf`` raises :class:`ValueError` naming the rows, which
    the caller reports in ``skipped`` instead of computing a NaN result (ISSUES P1-3).
    """
    frame = pd.read_csv(io.StringIO(eln.get_dataset_content(session, dataset.id)))
    if check:
        problems: list[str] = []
        for col in sorted(DATASET_NUMERIC_COLUMNS & set(frame.columns)):
            values = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)
            rows = [int(i) + 1 for i in np.flatnonzero(~np.isfinite(values))]
            if rows:
                shown = ", ".join(str(r) for r in rows[:5]) + (" …" if len(rows) > 5 else "")
                problems.append(f"{col} rows {shown}")
        if problems:
            raise ValueError(
                f"dataset {dataset.id} has missing or non-finite numeric values "
                f"({'; '.join(problems)}) — re-upload a corrected CSV (supersedes)"
            )
    return frame


def _non_finite_paths(value: Any, path: str = "") -> list[str]:
    """Paths of NaN/±inf floats inside a dumped output (``per_analyte[2].slope``)."""
    if isinstance(value, float):
        return [] if np.isfinite(value) else [path or "<root>"]
    if isinstance(value, dict):
        return [
            p for k, v in value.items() for p in _non_finite_paths(v, f"{path}.{k}" if path else k)
        ]
    if isinstance(value, list | tuple):
        return [p for i, v in enumerate(value) for p in _non_finite_paths(v, f"{path}[{i}]")]
    return []


_CALIBRATION_ALIASES: dict[str, str] = {
    "": "solvent",
    "solvent": "solvent",
    "matrix-matched": "matrix-matched",
    "matrix": "matrix-matched",
    "mm": "matrix-matched",
    "standard-addition": "standard-addition",
}


def _calibration_type(cond: ConditionBlock) -> tuple[calc.CalibrationType, str | None]:
    """``calibration_type`` of the condition block → (curve to quantify with, problem).

    Domain: ``solvent | matrix-matched | standard-addition`` (missing = ``solvent``).
    ``problem`` is the declared value when Analysis cannot honour it — ``standard-addition``
    (valid but not supported yet) or a value outside the domain. Such values are never
    silently treated as ``solvent``; the caller flags them and skips quantification.
    """
    raw = (cond.model_extra or {}).get("calibration_type")
    text = str(raw).strip().lower().replace("_", "-").replace(" ", "-") if raw else ""
    value = _CALIBRATION_ALIASES.get(text)
    if value == "matrix-matched":
        return "matrix-matched", None
    if value == "solvent":
        return "solvent", None
    return "solvent", str(raw)


# ------------------------------------------------------------ computations


def _residuals_out(item: calc.AnalyteCalibration) -> list[ResidualOut]:
    return [
        ResidualOut(
            injection_id=r.injection_id,
            level=r.level,
            response_ratio=r.response,
            predicted=r.predicted,
            residual=r.residual,
            back_calculated=r.back_calculated,
            relative_error_pct=r.relative_error_pct,
            standardized_residual=r.standardized,
        )
        for r in item.residuals
    ]


def _fit_line_points(item: calc.AnalyteCalibration) -> list[CalibrationPoint]:
    return [
        CalibrationPoint(
            level=b.level, response_ratio=item.fit.intercept + item.fit.slope * b.level
        )
        for b in item.back_calc
    ]


def _fit_out(item: calc.AnalyteCalibration) -> CalibrationFitOut:
    return CalibrationFitOut(
        weighting=item.fit.weighting,
        slope=item.fit.slope,
        intercept=item.fit.intercept,
        r_squared=item.fit.r_squared,
        residual_sd=item.fit.residual_sd,
        se_slope=item.fit.se_slope,
        se_intercept=item.fit.se_intercept,
        max_abs_back_calc_error_pct=item.max_abs_error_pct,
        sum_abs_relative_error_pct=item.sum_abs_error_pct,
        back_calc=[BackCalcLevelOut(**b.__dict__) for b in item.back_calc],
        fit_line=_fit_line_points(item),
        residuals=_residuals_out(item),
    )


def _calibration_output(
    frame: pd.DataFrame,
    weighting: calc.Weighting,
    c: AcceptanceCriteria,
    label: str,
    *,
    calibration_type: calc.CalibrationType = "solvent",
    curve_used: calc.CurveUsed = "dataset",
) -> tuple[CalibrationOutput, list[QCFlag], dict[str, calc.AnalyteCalibration]]:
    by_weighting = {w: calc.calibrate(frame, w) for w in calc.WEIGHTINGS}
    cal = by_weighting[weighting]
    analytes: list[AnalyteCalibrationOut] = []
    flags: list[QCFlag] = []
    heteroscedastic: list[str] = []
    for name, item in cal.items():
        group = frame[frame["analyte"] == name]
        ratios = calc.response_ratio(group)
        levels = group["level_ng_ml"].to_numpy(float)
        f_test = calc.heteroscedasticity_f_test(levels, ratios, c.heteroscedasticity_alpha)
        if f_test is not None and f_test.significant:
            heteroscedastic.append(name)
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
                points=[
                    CalibrationPoint(level=float(lv), response_ratio=float(r))
                    for lv, r in zip(levels, ratios, strict=True)
                ],
                fit_line=_fit_line_points(item),
                residual_sd=item.fit.residual_sd,
                se_slope=item.fit.se_slope,
                se_intercept=item.fit.se_intercept,
                residuals=_residuals_out(item),
                fits=[_fit_out(by_weighting[w][name]) for w in calc.WEIGHTINGS],
                heteroscedasticity=(
                    HeteroscedasticityOut(**f_test.__dict__) if f_test is not None else None
                ),
            )
        )
        flags += calibration_flags(name, item.fit.r_squared, item.max_abs_error_pct, c, label)
    comparison = [
        WeightingComparison(
            weighting=w,
            sum_abs_relative_error_pct=float(
                sum(a.sum_abs_error_pct for a in by_weighting[w].values())
            ),
        )
        for w in calc.WEIGHTINGS
    ]
    output = CalibrationOutput(
        weighting=weighting,
        analytes=analytes,
        weighting_comparison=comparison,
        calibration_type=calibration_type,
        curve_used=curve_used,
        heteroscedastic_analytes=heteroscedastic,
        method=method_doc("calibration"),
    )
    return output, flags, cal


def _limits_output(
    frame: pd.DataFrame,
    cal: dict[str, calc.AnalyteCalibration],
    c: AcceptanceCriteria,
    label: str,
    factor: float | None,
) -> tuple[LimitsOutput, list[QCFlag]]:
    analytes: list[AnalyteLimitsOut] = []
    flags: list[QCFlag] = []
    for name, group in frame.groupby("analyte", sort=True):
        analyte = str(name)
        x = group["level_ng_ml"].to_numpy(float)
        estimates = calc.detection_limits(
            x,
            calc.response_ratio(group),
            k_lod=c.lod_k,
            k_loq=c.loq_k,
            replicate_slope=cal[analyte].fit.slope,
            range_factor=c.lod_range_factor,
        )
        if not estimates:
            continue
        primary = calc.primary_limit(estimates)
        lowest = float(np.min(x))
        analytes.append(
            AnalyteLimitsOut(
                analyte=analyte,
                primary_method=primary.method,
                lod=primary.lod,
                loq=primary.loq,
                lod_ng_g=primary.lod * factor if factor else None,
                loq_ng_g=primary.loq * factor if factor else None,
                lowest_level=lowest,
                estimates=[LimitEstimateOut(**e.__dict__) for e in estimates],
            )
        )
        if (flag := loq_flag(analyte, primary.loq, lowest, label)) is not None:
            flags.append(flag)
    output = LimitsOutput(
        k_lod=c.lod_k, k_loq=c.loq_k, analytes=analytes, method=method_doc("limits")
    )
    return output, flags


def _recovery_output(
    frame: pd.DataFrame,
    cal: dict[str, calc.AnalyteCalibration],
    volume: float,
    mass: float,
    c: AcceptanceCriteria,
    label: str = DEFAULT_CRITERIA_LABEL,
    cal_no_is: dict[str, calc.AnalyteCalibration] | None = None,
) -> tuple[RecoveryOutput, list[QCFlag]]:
    rows, groups = calc.compute_recovery(
        frame, cal, extraction_volume_ml=volume, sample_mass_g=mass, calibration_no_is=cal_no_is
    )
    all_values = np.array([r.recovery_pct for r in rows])
    mean, _sd, rsd = calc.summary_stats(all_values)
    flags: list[QCFlag] = []
    group_out: list[RecoveryGroupOut] = []
    for g in groups:
        flags += recovery_flags(g.analyte, g.spike_ng_g, g.mean_pct, g.rsd_pct, c, label)
        members = [r for r in rows if r.analyte == g.analyte and r.spike_ng_g == g.spike_ng_g]
        no_is = [r.recovery_no_is_pct for r in members if r.recovery_no_is_pct is not None]
        grubbs = calc.grubbs_test(np.array([r.recovery_pct for r in members]), c.grubbs_alpha)
        grubbs_out: GrubbsOut | None = None
        if grubbs is not None:
            suspect = members[grubbs.suspect_index].injection_id
            grubbs_out = GrubbsOut(
                n=grubbs.n,
                g_statistic=grubbs.g_statistic,
                g_critical=grubbs.g_critical,
                alpha=grubbs.alpha,
                suspect_injection_id=suspect,
                suspect_value=grubbs.suspect_value,
                is_outlier=grubbs.is_outlier,
            )
            if grubbs.is_outlier:
                flags.append(
                    outlier_flag(
                        g.analyte,
                        g.spike_ng_g,
                        suspect,
                        grubbs.g_statistic,
                        grubbs.g_critical,
                        grubbs.alpha,
                        label,
                    )
                )
        group_out.append(
            RecoveryGroupOut(
                **g.__dict__,
                mean_no_is_pct=float(np.mean(no_is)) if len(no_is) == len(members) else None,
                grubbs=grubbs_out,
            )
        )
    uncertainty: list[UncertaintyOut] = []
    for analyte in sorted({g.analyte for g in groups}):
        u = calc.recovery_uncertainty(
            analyte,
            groups,
            coverage_factor=c.coverage_factor,
            u_cref_pct=c.spike_uncertainty_pct,
        )
        uncertainty.append(UncertaintyOut(**u.__dict__))
        if (flag := uncertainty_flag(analyte, u.expanded_pct, c, label)) is not None:
            flags.append(flag)
    return (
        RecoveryOutput(
            overall_mean_pct=mean,
            overall_rsd_pct=rsd,
            n=len(rows),
            groups=group_out,
            rows=[RecoveryRowOut(**r.__dict__) for r in rows],
            uncertainty=uncertainty,
            method=method_doc("recovery"),
        ),
        flags,
    )


def _is_output(
    cal_frame: pd.DataFrame,
    sample_frame: pd.DataFrame,
    c: AcceptanceCriteria,
    label: str = DEFAULT_CRITERIA_LABEL,
) -> tuple[ISResponseOutput, list[QCFlag]]:
    reference, injections = calc.compute_is_response(cal_frame, sample_frame)
    _ref, cal_injections = calc.calibration_is_reference(cal_frame)
    _mean, _sd, ref_rsd = calc.summary_stats(np.array([i.is_area for i in cal_injections]))
    flags: list[QCFlag] = []
    out: list[ISInjectionOut] = []
    for inj in injections:
        flag = is_response_flag(inj.injection_id, inj.sample_id, inj.response_pct, c, label)
        if flag is not None:
            flags.append(flag)
        out.append(ISInjectionOut(**inj.__dict__, flagged=flag is not None))
    cal_out = [
        ISInjectionOut(
            **inj.__dict__,
            flagged=not c.is_response_min_pct <= inj.response_pct <= c.is_response_max_pct,
            role="calibration",
        )
        for inj in cal_injections
    ]
    return (
        ISResponseOutput(
            reference_is_area=reference,
            injections=out,
            flagged_count=len(flags),
            reference_is_rsd_pct=ref_rsd,
            calibration_injections=cal_out,
            method=method_doc("is_response"),
        ),
        flags,
    )


def _matrix_output(
    frame: pd.DataFrame, c: AcceptanceCriteria, label: str = DEFAULT_CRITERIA_LABEL
) -> tuple[MatrixEffectOutput, list[QCFlag]]:
    effects = calc.compute_matrix_effect(frame)
    flags = [
        f for e in effects if (f := matrix_effect_flag(e.analyte, e.matrix_effect_pct, c, label))
    ]
    return (
        MatrixEffectOutput(
            analytes=[MatrixEffectOut(**e.__dict__) for e in effects],
            method=method_doc("matrix_effect"),
        ),
        flags,
    )


def _ion_ratio_output(
    frame: pd.DataFrame, c: AcceptanceCriteria, label: str = DEFAULT_CRITERIA_LABEL
) -> tuple[IonRatioOutput, list[QCFlag]]:
    rows = calc.compute_ion_ratios(frame)
    flags: list[QCFlag] = []
    out: list[IonRatioRowOut] = []
    for r in rows:
        flag = ion_ratio_flag(r.analyte, r.injection_id, r.deviation_pct, c, label)
        if flag is not None:
            flags.append(flag)
        out.append(IonRatioRowOut(**r.__dict__, flagged=flag is not None))
    return (
        IonRatioOutput(
            tolerance_pct=c.ion_ratio_tolerance_pct,
            rows=out,
            flagged_count=len(flags),
            method=method_doc("ion_ratio"),
        ),
        flags,
    )


def run_experiment(session: Session, experiment_id: int, *, actor: Actor = "user") -> RunResponse:
    """Run every applicable analysis for an experiment's latest dataset of each kind.

    Results are judged against the project's active criteria version; identical inputs
    (datasets, parameters, criteria) reuse the stored result instead of a new row.
    Data problems (missing curve, non-positive slope, …) are reported in ``skipped``.
    """
    exp = eln.get_experiment(session, experiment_id)
    version = get_project_criteria(session, exp.project_id).active
    criteria, label = version.criteria, version.label
    crit_params = _criteria_params(version)
    latest: dict[str, DatasetOut] = {}
    for ds in eln.list_datasets(session, experiment_id):
        latest[ds.kind] = ds  # later uploads supersede earlier ones of the same kind
    # ELN-7 ``ion_ratio@1`` datasets only (the pre-ELN-7 ``other`` fallback was removed).
    ion_ds = latest.get("ion_ratio")
    cond = exp.condition_block
    weighting: calc.Weighting = cond.calibration_weighting or "none"
    calibration_type, unsupported_type = _calibration_type(cond)
    factor = (
        cond.extraction_volume_ml / cond.sample_mass_g
        if cond.extraction_volume_ml and cond.sample_mass_g
        else None
    )
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
        bad = _non_finite_paths(output.model_dump(mode="python")) + [
            f"flags[{i}].value" for i, f in enumerate(flags) if not np.isfinite(f.value)
        ]
        if bad:
            # Last line of defence: a NaN/inf never becomes an immutable stored result.
            skipped.append(
                f"{kind}: non-finite values in output ({', '.join(bad[:3])}) — not stored"
            )
            return
        result, is_new = _store(
            session,
            experiment_id=experiment_id,
            project_id=exp.project_id,
            kind=kind,
            datasets=datasets,
            params={**params, **crit_params},
            output=output,
            flags=flags,
            actor=actor,
        )
        results.append(result)
        created += int(is_new)

    cal_ds = latest.get("calibration")
    cal_frame: pd.DataFrame | None = None
    cal_map: dict[str, calc.AnalyteCalibration] | None = None
    cal_params: dict[str, Any] = {"weighting": weighting, "calibration_type": calibration_type}
    if unsupported_type is not None:
        cal_params["calibration_type_declared"] = unsupported_type
    if cal_ds is not None:
        try:
            cal_frame, curve_used = calc.select_calibration_curve(
                _frame(session, cal_ds), calibration_type
            )
            cal_out, cal_flags, cal_map = _calibration_output(
                cal_frame,
                weighting,
                criteria,
                label,
                calibration_type=calibration_type,
                curve_used=curve_used,
            )
        except ValueError as exc:
            skipped.append(f"calibration: {exc}")
            cal_frame, cal_map = None, None
        else:
            cal_params["curve_used"] = curve_used
            if unsupported_type is not None:
                cal_flags = [
                    *cal_flags,
                    calibration_type_flag(
                        unsupported_type,
                        SUPPORTED_CALIBRATION_TYPES,
                        len(_frame(session, rec, check=False))
                        if (rec := latest.get("recovery"))
                        else 0,
                        label,
                    ),
                ]
            store("calibration", [cal_ds], cal_params, cal_out, cal_flags)
            try:
                lim_out, lim_flags = _limits_output(cal_frame, cal_map, criteria, label, factor)
            except ValueError as exc:
                skipped.append(f"limits: {exc}")
            else:
                store("limits", [cal_ds], {**cal_params, "unit_factor": factor}, lim_out, lim_flags)

    rec_ds = latest.get("recovery")
    if rec_ds is not None:
        if unsupported_type is not None:
            skipped.append(
                f"recovery: calibration_type '{unsupported_type}' is not supported by Analysis "
                f"(supported: {', '.join(SUPPORTED_CALIBRATION_TYPES)})"
            )
        elif cal_ds is None or cal_map is None or cal_frame is None:
            skipped.append("recovery: experiment has no calibration dataset")
        elif cond.extraction_volume_ml is None or cond.sample_mass_g is None:
            skipped.append("recovery: condition block lacks extraction_volume_ml/sample_mass_g")
        else:
            params = {
                **cal_params,
                "extraction_volume_ml": cond.extraction_volume_ml,
                "sample_mass_g": cond.sample_mass_g,
            }
            try:
                rec_frame = _frame(session, rec_ds)
                cal_no_is = calc.calibrate(cal_frame, weighting, use_is=False)
                rec_out, rec_flags = _recovery_output(
                    rec_frame,
                    cal_map,
                    cond.extraction_volume_ml,
                    cond.sample_mass_g,
                    criteria,
                    label,
                    cal_no_is,
                )
            except ValueError as exc:
                skipped.append(f"recovery: {exc}")
            else:
                store("recovery", [cal_ds, rec_ds], params, rec_out, rec_flags)
                is_out, is_flags = _is_output(cal_frame, rec_frame, criteria, label)
                store("is_response", [cal_ds, rec_ds], {}, is_out, is_flags)

    me_ds = latest.get("matrix_effect")
    if me_ds is not None:
        try:
            me_out, me_flags = _matrix_output(_frame(session, me_ds), criteria, label)
        except ValueError as exc:
            skipped.append(f"matrix_effect: {exc}")
        else:
            store("matrix_effect", [me_ds], {}, me_out, me_flags)

    if ion_ds is not None:
        try:
            ion_out, ion_flags = _ion_ratio_output(_frame(session, ion_ds), criteria, label)
        except ValueError as exc:
            skipped.append(f"ion_ratio: {exc}")
        else:
            store("ion_ratio", [ion_ds], {}, ion_out, ion_flags)
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


def list_methods() -> list[MethodDoc]:
    """Formula sheets of every current method version (and the comparison)."""
    return all_method_docs()


def get_result(session: Session, result_id: int) -> AnalysisResultOut:
    """One stored result by id."""
    row = session.get(AnalysisResult, result_id)
    if row is None:
        raise NotFoundError(f"AnalysisResult {result_id} not found")
    return _to_out(row)


def list_results(
    session: Session, experiment_id: int | None = None, kind: ResultKind | None = None
) -> list[AnalysisResultOut]:
    """Stored results, oldest first, optionally filtered by experiment and kind."""
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


#: Experiment ids per batched ``IN (...)`` query.
_IN_CHUNK = 500


def _latest_ids(experiment_ids: list[int]) -> Any:
    """``SELECT`` of the newest result id per (experiment, kind) of ``experiment_ids``."""
    return (
        select(func.max(AnalysisResult.id))
        .where(AnalysisResult.experiment_id.in_(experiment_ids))
        .group_by(AnalysisResult.experiment_id, AnalysisResult.kind)
    )


def latest_result_ids_many(
    session: Session, experiment_ids: list[int]
) -> dict[int, dict[ResultKind, int]]:
    """Id of the latest result of each kind for many experiments (no JSON column read).

    Every requested id is a key; kinds in the order of :func:`latest_results`.
    """
    out: dict[int, dict[ResultKind, int]] = {i: {} for i in experiment_ids}
    unique = sorted(set(experiment_ids))
    for start in range(0, len(unique), _IN_CHUNK):
        rows = session.execute(
            select(AnalysisResult.id, AnalysisResult.experiment_id, AnalysisResult.kind)
            .where(AnalysisResult.id.in_(_latest_ids(unique[start : start + _IN_CHUNK])))
            .order_by(AnalysisResult.experiment_id, AnalysisResult.kind)
        )
        for rid, exp_id, kind in rows:
            out[exp_id][cast(ResultKind, kind)] = rid
    return out


_HEAD_COLUMNS = (
    AnalysisResult.id,
    AnalysisResult.experiment_id,
    AnalysisResult.kind,
    AnalysisResult.method_version,
    type_coerce(AnalysisResult.flags, Text),  # JSON text, validated in one pass
)
_FLAGS: TypeAdapter[list[QCFlag]] = TypeAdapter(list[QCFlag])


def _head(row: Any) -> ResultHead:
    rid, exp_id, kind, method_version, flags = row
    return ResultHead(
        id=rid,
        experiment_id=exp_id,
        kind=kind,
        method_version=method_version,
        flags=_FLAGS.validate_json(flags),
    )


def get_result_heads(session: Session, result_ids: list[int]) -> dict[int, ResultHead]:
    """Stored results by id without their (large) outputs, batched; missing ids are absent."""
    out: dict[int, ResultHead] = {}
    for start in range(0, len(result_ids), _IN_CHUNK):
        chunk = result_ids[start : start + _IN_CHUNK]
        for row in session.execute(select(*_HEAD_COLUMNS).where(AnalysisResult.id.in_(chunk))):
            head = _head(row)
            out[head.id] = head
    return out


def latest_result_refs_many(
    session: Session, experiment_ids: list[int]
) -> dict[int, dict[ResultKind, ResultHead]]:
    """The latest result of each kind (without output) for many experiments.

    Every requested id is a key (``{}`` without stored results). Per experiment the kinds
    come in the order of :func:`latest_results`.
    """
    out: dict[int, dict[ResultKind, ResultHead]] = {i: {} for i in experiment_ids}
    unique = sorted(set(experiment_ids))
    for start in range(0, len(unique), _IN_CHUNK):
        rows = session.execute(
            select(*_HEAD_COLUMNS)
            .where(AnalysisResult.id.in_(_latest_ids(unique[start : start + _IN_CHUNK])))
            .order_by(AnalysisResult.experiment_id, AnalysisResult.kind)
        )
        for row in rows:
            head = _head(row)
            out[head.experiment_id][head.kind] = head
    return out


def _result_views_many(
    session: Session, experiment_ids: list[int]
) -> dict[int, dict[ResultKind, ResultView]]:
    """Metric views of the latest result of each kind (kinds in :func:`latest_results` order).

    The stored output JSON is read as text and validated straight into the light views of
    :mod:`app.analysis.metrics_view` — one query per 500 experiments.
    """
    out: dict[int, dict[ResultKind, ResultView]] = {i: {} for i in experiment_ids}
    unique = sorted(set(experiment_ids))
    for start in range(0, len(unique), _IN_CHUNK):
        rows = session.execute(
            select(
                AnalysisResult.id,
                AnalysisResult.experiment_id,
                AnalysisResult.kind,
                AnalysisResult.method_version,
                AnalysisResult.parameters,
                type_coerce(AnalysisResult.flags, Text),
                type_coerce(AnalysisResult.output, Text),
            )
            .where(AnalysisResult.id.in_(_latest_ids(unique[start : start + _IN_CHUNK])))
            .order_by(AnalysisResult.experiment_id, AnalysisResult.kind)
        )
        for rid, exp_id, kind, method_version, parameters, flags, output in rows:
            out[exp_id][kind] = ResultView(
                id=rid,
                kind=kind,
                method_version=method_version,
                parameters=parameters,
                flags=_FLAGS.validate_json(flags),
                output=OUTPUT_VIEW.validate_json(output),
            )
    return out


def get_metrics(session: Session, experiment_id: int) -> ExperimentMetrics:
    """Headline metrics assembled from the latest stored results (no recomputation)."""
    eln.get_experiment(session, experiment_id)
    return _metrics(experiment_id, _result_views_many(session, [experiment_id])[experiment_id])


def get_metrics_many(session: Session, experiment_ids: list[int]) -> dict[int, ExperimentMetrics]:
    """:func:`get_metrics` of many existing experiments, read in batches (no per-id query)."""
    views = _result_views_many(session, experiment_ids)
    return {i: _metrics(i, views[i]) for i in experiment_ids}


def get_metrics_and_heads_many(
    session: Session, experiment_ids: list[int]
) -> tuple[dict[int, ExperimentMetrics], dict[int, dict[ResultKind, ResultHead]]]:
    """:func:`get_metrics_many` and :func:`latest_result_refs_many` from one read of the rows."""
    views = _result_views_many(session, experiment_ids)
    metrics = {i: _metrics(i, views[i]) for i in experiment_ids}
    heads = {
        i: {
            kind: ResultHead(
                id=v.id,
                experiment_id=i,
                kind=kind,
                method_version=v.method_version,
                flags=v.flags,
            )
            for kind, v in views[i].items()
        }
        for i in experiment_ids
    }
    return metrics, heads


def _metrics(experiment_id: int, latest: dict[ResultKind, ResultView]) -> ExperimentMetrics:
    """Headline metrics of an experiment from its latest stored result of each kind."""
    if not latest:
        return ExperimentMetrics(experiment_id=experiment_id, analyzed=False)
    flags = [f for r in latest.values() for f in r.flags]
    m = ExperimentMetrics(
        experiment_id=experiment_id,
        analyzed=True,
        source_result_ids=sorted(r.id for r in latest.values()),
        flags=flags,
        qc_status=overall_status(flags),
        criteria_versions=sorted(
            {
                str(r.parameters["criteria_version"])
                for r in latest.values()
                if "criteria_version" in r.parameters
            }
        ),
    )
    analytes: set[str] = {f.analyte for f in flags if f.analyte}
    if (rec := latest.get("recovery")) and isinstance(rec.output, RecoveryView):
        m.recovery_mean_pct = rec.output.overall_mean_pct
        m.recovery_rsd_pct = rec.output.overall_rsd_pct
        m.recovery_n = rec.output.n
        for analyte in sorted({r.analyte for r in rec.output.rows}):
            vals = np.array([r.recovery_pct for r in rec.output.rows if r.analyte == analyte])
            mean, _sd, rsd = calc.summary_stats(vals)
            m.per_analyte_recovery.append(
                AnalyteRecoverySummary(analyte=analyte, mean_pct=mean, rsd_pct=rsd, n=vals.size)
            )
            analytes.add(analyte)
        m.expanded_uncertainty_pct = {u.analyte: u.expanded_pct for u in rec.output.uncertainty}
        m.outlier_count = sum(1 for g in rec.output.groups if g.grubbs and g.grubbs.is_outlier)
    if (cal := latest.get("calibration")) and isinstance(cal.output, CalibrationView):
        m.min_r_squared = min(a.r_squared for a in cal.output.analytes)
        m.max_abs_back_calc_error_pct = max(
            a.max_abs_back_calc_error_pct for a in cal.output.analytes
        )
        m.calibration_weighting = cal.output.weighting
        analytes.update(a.analyte for a in cal.output.analytes)
    if (isr := latest.get("is_response")) and isinstance(isr.output, ISResponseView):
        m.is_injections_total = len(isr.output.injections)
        m.is_injections_flagged = isr.output.flagged_count
    if (me := latest.get("matrix_effect")) and isinstance(me.output, MatrixEffectView):
        m.matrix_effect_pct = {a.analyte: a.matrix_effect_pct for a in me.output.analytes}
        analytes.update(m.matrix_effect_pct)
    if (lim := latest.get("limits")) and isinstance(lim.output, LimitsView):
        m.limits = [
            AnalyteLimitsSummary(
                analyte=a.analyte,
                lod=a.lod,
                loq=a.loq,
                unit=lim.output.unit,
                method=a.primary_method,
            )
            for a in lim.output.analytes
        ]
    if (ion := latest.get("ion_ratio")) and isinstance(ion.output, IonRatioView):
        m.ion_ratio_injections_flagged = ion.output.flagged_count
    m.qc_verdicts = verdicts(analytes, flags)
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
    """Numerical comparison of experiment ``b`` against ``a``.

    Overall and per-analyte Welch t-tests with mean difference, CI and effect sizes;
    per-analyte p-values are Holm-adjusted and judged at the comparison α of the
    active criteria of ``b``'s project. Formulas/assumptions are in ``method``.
    """
    ma, mb = get_metrics(session, a), get_metrics(session, b)
    exp_b = eln.get_experiment(session, b)
    alpha = get_project_criteria(session, exp_b.project_id).active.criteria.comparison_alpha
    va, vb = _recovery_values(session, a), _recovery_values(session, b)
    per_analyte: list[AnalyteDelta] = []
    tested: list[int] = []
    for name in sorted(set(va) & set(vb)):
        xa, xb = np.array(va[name]), np.array(vb[name])
        delta = AnalyteDelta(
            analyte=name,
            mean_a_pct=float(np.mean(xa)),
            mean_b_pct=float(np.mean(xb)),
            delta_pct_points=float(np.mean(xb) - np.mean(xa)),
            n_a=int(xa.size),
            n_b=int(xb.size),
        )
        if xa.size >= 2 and xb.size >= 2:
            try:
                w = calc.welch_t_test(xa, xb, 1.0 - alpha)
            except ValueError:
                pass
            else:
                delta.t_statistic = w.t_statistic
                delta.df = w.df
                delta.p_value = w.p_value
                delta.ci_low, delta.ci_high = w.ci_low, w.ci_high
                delta.cohens_d, delta.hedges_g = w.cohens_d, w.hedges_g
                tested.append(len(per_analyte))
        per_analyte.append(delta)
    # ``tested`` holds only analytes whose Welch test produced a p-value; an underflowed
    # p = 0.0 is a real (very small) p-value and must not become 1.0 (ISSUES P1-5).
    adjusted = calc.holm_adjust(
        [1.0 if (p := per_analyte[i].p_value) is None else p for i in tested]
    )
    for i, p_holm in zip(tested, adjusted, strict=True):
        per_analyte[i].p_holm = p_holm
        per_analyte[i].significant = p_holm < alpha
    t_test: RecoveryTTest | None = None
    flat_a = np.array([v for vs in va.values() for v in vs])
    flat_b = np.array([v for vs in vb.values() for v in vs])
    if flat_a.size >= 2 and flat_b.size >= 2:
        try:
            w = calc.welch_t_test(flat_a, flat_b, 1.0 - alpha)
        except ValueError:
            pass
        else:
            t_test = RecoveryTTest(**w.__dict__)
    delta_mean = (
        mb.recovery_mean_pct - ma.recovery_mean_pct
        if ma.recovery_mean_pct is not None and mb.recovery_mean_pct is not None
        else None
    )
    return MetricsComparison(
        experiment_a=a,
        experiment_b=b,
        metrics_a=ma,
        metrics_b=mb,
        recovery_delta_pct_points=delta_mean,
        per_analyte=per_analyte,
        recovery_t_test=t_test,
        alpha=alpha,
        significant_analytes=[d.analyte for d in per_analyte if d.significant],
        method=comparison_doc(),
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
                flag_count=sum(1 for f in m.flags if f.severity != "info"),
                info_flag_count=sum(1 for f in m.flags if f.severity == "info"),
                source_result_ids=m.source_result_ids,
            )
        )
    return points


def build_report(
    session: Session, experiment_id: int, fmt: ReportFormat = "markdown"
) -> tuple[str, str, str]:
    """Render the latest stored results as ``(text, media_type, filename)``."""
    exp = eln.get_experiment(session, experiment_id)
    metrics = get_metrics(session, experiment_id)
    results = latest_results(session, experiment_id)
    stem = f"biopilot-{exp.code.lstrip('#')}-analysis"
    if fmt == "csv":
        return render_csv(exp, metrics, results), "text/csv", f"{stem}.csv"
    return render_markdown(exp, metrics, results), "text/markdown", f"{stem}.md"
