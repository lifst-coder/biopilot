"""Export of stored analysis results as Markdown or CSV (no recomputation).

The report only *formats* values already stored in :class:`AnalysisResult` rows and the
metrics assembled from them; every section names its source result id and method
version, and the Markdown report appends the formula sheet used for each result.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from app.analysis.schemas import (
    AnalysisResultOut,
    CalibrationOutput,
    ExperimentMetrics,
    IonRatioOutput,
    ISResponseOutput,
    LimitsOutput,
    MatrixEffectOutput,
    MethodDoc,
    RecoveryOutput,
    ResultKind,
)
from app.eln.schemas import ExperimentOut

_ORDER: tuple[ResultKind, ...] = (
    "calibration",
    "limits",
    "recovery",
    "is_response",
    "matrix_effect",
    "ion_ratio",
)


def _num(value: float | None, digits: int = 2) -> str:
    """Fixed-point rendering of a stored value (``—`` for missing)."""
    if value is None:
        return "—"
    if value != 0 and abs(value) < 10 ** (-digits):
        return f"{value:.3e}"
    return f"{value:.{digits}f}"


def _cell(text: str) -> str:
    """Escape Markdown table separators inside a cell."""
    return text.replace("|", "\\|")


def _table(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(map(_cell, headers)) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(map(_cell, r)) + " |" for r in rows]
    return [*lines, ""]


def _method_section(doc: MethodDoc) -> list[str]:
    lines = [f"**공식** ({doc.version})", ""]
    lines += [f"- `{f}`" for f in doc.formulas]
    lines += ["", "**가정**", ""]
    lines += [f"- {a}" for a in doc.assumptions]
    if doc.references:
        lines += ["", "**참고**: " + "; ".join(doc.references)]
    return [*lines, ""]


def render_markdown(
    experiment: ExperimentOut,
    metrics: ExperimentMetrics,
    results: dict[ResultKind, AnalysisResultOut],
) -> str:
    """Human-readable report of the latest stored results of one experiment."""
    lines = [
        f"# 분석 리포트 — {experiment.code} {experiment.title}",
        "",
        f"- 실험 ID: {experiment.id} · 수행일: {experiment.performed_on.isoformat()}",
        f"- QC 판정: **{metrics.qc_status}** · 기준 버전: "
        f"{', '.join(metrics.criteria_versions) or '—'}",
        f"- 근거 결과: {', '.join(f'#{i}' for i in metrics.source_result_ids) or '—'}",
        "",
        "> 모든 수치는 저장된 AnalysisResult에서 그대로 옮긴 값이다(재계산 없음).",
        "",
    ]
    if metrics.qc_verdicts:
        lines += ["## QC 판정 (분석물별)", ""]
        lines += _table(
            ["분석물", "판정", "불합격 항목", "경고 항목"],
            (
                [
                    v.analyte,
                    v.status,
                    ", ".join(v.failed_checks) or "—",
                    ", ".join(v.warning_checks) or "—",
                ]
                for v in metrics.qc_verdicts
            ),
        )
    for kind in _ORDER:
        res = results.get(kind)
        if res is None:
            continue
        out = res.output
        lines += [f"## {kind} — 결과 #{res.id} ({res.method_version})", ""]
        if isinstance(out, CalibrationOutput):
            lines += [f"가중 `{out.weighting}` · 곡선 `{out.curve_used}`", ""]
            lines += _table(
                ["분석물", "기울기", "절편", "R²", "s(res)", "최대 |%RE|", "F-검정 p"],
                (
                    [
                        a.analyte,
                        _num(a.slope, 6),
                        _num(a.intercept, 6),
                        _num(a.r_squared, 5),
                        _num(a.residual_sd, 6),
                        _num(a.max_abs_back_calc_error_pct),
                        _num(a.heteroscedasticity.p_value, 4) if a.heteroscedasticity else "—",
                    ]
                    for a in out.analytes
                ),
            )
            lines += _table(
                ["가중", "Σ|%RE|"],
                (
                    [w.weighting, _num(w.sum_abs_relative_error_pct)]
                    for w in out.weighting_comparison
                ),
            )
        elif isinstance(out, LimitsOutput):
            lines += _table(
                [
                    "분석물",
                    "방법",
                    f"LOD ({out.unit})",
                    f"LOQ ({out.unit})",
                    "LOD (ng/g)",
                    "LOQ (ng/g)",
                ],
                (
                    [
                        a.analyte,
                        a.primary_method,
                        _num(a.lod, 3),
                        _num(a.loq, 3),
                        _num(a.lod_ng_g, 3),
                        _num(a.loq_ng_g, 3),
                    ]
                    for a in out.analytes
                ),
            )
        elif isinstance(out, RecoveryOutput):
            lines += [
                f"전체 평균 {_num(out.overall_mean_pct, 1)} % · RSD "
                f"{_num(out.overall_rsd_pct, 1)} % · n = {out.n}",
                "",
            ]
            lines += _table(
                ["분석물", "첨가 (ng/g)", "n", "평균 %", "RSD %", "IS 미보정 평균 %", "Grubbs"],
                (
                    [
                        g.analyte,
                        _num(g.spike_ng_g, 1),
                        str(g.n),
                        _num(g.mean_pct, 1),
                        _num(g.rsd_pct, 1),
                        _num(g.mean_no_is_pct, 1),
                        (
                            f"G={_num(g.grubbs.g_statistic)}/{_num(g.grubbs.g_critical)}"
                            + (f" ({g.grubbs.suspect_injection_id})" if g.grubbs.is_outlier else "")
                            if g.grubbs
                            else "—"
                        ),
                    ]
                    for g in out.groups
                ),
            )
            lines += _table(
                ["분석물", "u(Rw) %", "u(bias) %", "u_c %", "k", "U %"],
                (
                    [
                        u.analyte,
                        _num(u.u_rw_pct, 1),
                        _num(u.u_bias_pct, 1),
                        _num(u.u_combined_pct, 1),
                        _num(u.coverage_factor, 1),
                        _num(u.expanded_pct, 1),
                    ]
                    for u in out.uncertainty
                ),
            )
        elif isinstance(out, ISResponseOutput):
            lines += [
                f"기준 IS 면적 {_num(out.reference_is_area, 0)} · 이탈 "
                f"{out.flagged_count}/{len(out.injections)}",
                "",
            ]
            lines += _table(
                ["주입", "시료", "IS 면적", "응답 %", "이탈"],
                (
                    [
                        i.injection_id,
                        i.sample_id,
                        _num(i.is_area, 0),
                        _num(i.response_pct, 1),
                        "예" if i.flagged else "",
                    ]
                    for i in out.injections
                ),
            )
        elif isinstance(out, MatrixEffectOutput):
            lines += _table(
                ["분석물", "기울기(용매)", "기울기(매트릭스)", "ME %"],
                (
                    [
                        a.analyte,
                        _num(a.slope_solvent, 2),
                        _num(a.slope_matrix, 2),
                        _num(a.matrix_effect_pct, 1),
                    ]
                    for a in out.analytes
                ),
            )
        elif isinstance(out, IonRatioOutput):
            lines += _table(
                ["주입", "분석물", "이온비", "기준", "편차 %", "이탈"],
                (
                    [
                        r.injection_id,
                        r.analyte,
                        _num(r.ion_ratio, 4),
                        _num(r.reference_ratio, 4),
                        _num(r.deviation_pct, 1),
                        "예" if r.flagged else "",
                    ]
                    for r in out.rows
                ),
            )
        if res.flags:
            lines += _table(
                ["플래그", "심각도", "대상", "값", "기준"],
                (
                    [
                        f.code,
                        f.severity,
                        f.analyte or str(f.context.get("injection_id", "—")),
                        _num(f.value),
                        f"{_num(f.threshold_low)} – {_num(f.threshold_high)}",
                    ]
                    for f in res.flags
                ),
            )
        if out.method is not None:
            lines += _method_section(out.method)
    return "\n".join(lines).rstrip() + "\n"


CSV_HEADER = ["section", "result_id", "method_version", "analyte", "key", "metric", "value", "unit"]


def render_csv(
    experiment: ExperimentOut,
    metrics: ExperimentMetrics,
    results: dict[ResultKind, AnalysisResultOut],
) -> str:
    """Long-format CSV (one value per row) of the latest stored results."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)

    def row(
        res: AnalysisResultOut | None,
        section: str,
        analyte: str,
        key: str,
        metric: str,
        value: float | int | str | None,
        unit: str = "",
    ) -> None:
        writer.writerow(
            [
                section,
                res.id if res else "",
                res.method_version if res else "",
                analyte,
                key,
                metric,
                "" if value is None else value,
                unit,
            ]
        )

    row(None, "experiment", "", experiment.code, "qc_status", metrics.qc_status)
    for v in metrics.qc_verdicts:
        row(None, "verdict", v.analyte, "", "status", v.status)
    for kind in _ORDER:
        res = results.get(kind)
        if res is None:
            continue
        out = res.output
        if isinstance(out, CalibrationOutput):
            for a in out.analytes:
                row(res, kind, a.analyte, out.weighting, "slope", a.slope)
                row(res, kind, a.analyte, out.weighting, "intercept", a.intercept)
                row(res, kind, a.analyte, out.weighting, "r_squared", a.r_squared)
                row(res, kind, a.analyte, out.weighting, "residual_sd", a.residual_sd)
                row(
                    res,
                    kind,
                    a.analyte,
                    out.weighting,
                    "max_abs_re",
                    a.max_abs_back_calc_error_pct,
                    "%",
                )
                for r in a.residuals:
                    row(
                        res,
                        kind,
                        a.analyte,
                        r.injection_id,
                        "relative_error",
                        r.relative_error_pct,
                        "%",
                    )
                if a.heteroscedasticity is not None:
                    row(res, kind, a.analyte, "", "f_test_p", a.heteroscedasticity.p_value)
            for w in out.weighting_comparison:
                row(res, kind, "", w.weighting, "sum_abs_re", w.sum_abs_relative_error_pct, "%")
        elif isinstance(out, LimitsOutput):
            for lim in out.analytes:
                row(res, kind, lim.analyte, lim.primary_method, "lod", lim.lod, out.unit)
                row(res, kind, lim.analyte, lim.primary_method, "loq", lim.loq, out.unit)
                row(res, kind, lim.analyte, lim.primary_method, "lod", lim.lod_ng_g, "ng/g")
                row(res, kind, lim.analyte, lim.primary_method, "loq", lim.loq_ng_g, "ng/g")
        elif isinstance(out, RecoveryOutput):
            row(res, kind, "", "overall", "mean", out.overall_mean_pct, "%")
            row(res, kind, "", "overall", "rsd", out.overall_rsd_pct, "%")
            for g in out.groups:
                key = f"spike={g.spike_ng_g:g}"
                row(res, kind, g.analyte, key, "n", g.n)
                row(res, kind, g.analyte, key, "mean", g.mean_pct, "%")
                row(res, kind, g.analyte, key, "rsd", g.rsd_pct, "%")
                row(res, kind, g.analyte, key, "mean_no_is", g.mean_no_is_pct, "%")
            for u in out.uncertainty:
                row(
                    res,
                    kind,
                    u.analyte,
                    f"k={u.coverage_factor:g}",
                    "expanded_u",
                    u.expanded_pct,
                    "%",
                )
            for rr in out.rows:
                row(res, kind, rr.analyte, rr.injection_id, "recovery", rr.recovery_pct, "%")
        elif isinstance(out, ISResponseOutput):
            for i in out.injections:
                row(res, kind, "", i.injection_id, "is_response", i.response_pct, "%")
        elif isinstance(out, MatrixEffectOutput):
            for m in out.analytes:
                row(res, kind, m.analyte, "", "matrix_effect", m.matrix_effect_pct, "%")
        elif isinstance(out, IonRatioOutput):
            for ir in out.rows:
                row(
                    res,
                    kind,
                    ir.analyte,
                    ir.injection_id,
                    "ion_ratio_deviation",
                    ir.deviation_pct,
                    "%",
                )
        for f in res.flags:
            target = f.analyte or str(f.context.get("injection_id", ""))
            row(res, "flag", target, f.code, f.severity, f.value)
    return buf.getvalue()
