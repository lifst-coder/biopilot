"""Builds the grounded context (facts + evidence list) that every Partner engine consumes.

This is the *only* place Partner reads other modules, and it does so exclusively via
their service interfaces. Every number an engine may mention is materialised here as
an :class:`~app.partner.schemas.Evidence` with a reference to the stored record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.analysis.schemas import (
    AcceptanceCriteria,
    AnalysisResultOut,
    CalibrationOutput,
    ExperimentMetrics,
    MetricsComparison,
    ResultKind,
)
from app.eln import service as eln
from app.eln.schemas import ExperimentOut
from app.memory import service as memory
from app.memory.schemas import ExperimentDiff
from app.partner.schemas import CritiqueDraft, Evidence


def format_value(value: object) -> str:
    """Render condition values compactly (``10.0`` → ``10``; ``None`` → ``—``)."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


@dataclass
class EvidenceBook:
    """Accumulates evidence with stable keys ``E1, E2, …`` and semantic names."""

    items: list[Evidence] = field(default_factory=list)
    by_name: dict[str, Evidence] = field(default_factory=dict)

    def add(self, name: str, **fields: object) -> Evidence:
        ev = Evidence(key=f"E{len(self.items) + 1}", **fields)
        self.items.append(ev)
        self.by_name[name] = ev
        return ev

    def get(self, name: str) -> Evidence | None:
        return self.by_name.get(name)


@dataclass
class CritiqueContext:
    experiment: ExperimentOut
    baseline: ExperimentOut | None
    diff: ExperimentDiff | None
    metrics: ExperimentMetrics
    comparison: MetricsComparison | None
    results: dict[ResultKind, AnalysisResultOut]
    criteria: AcceptanceCriteria
    evidence: EvidenceBook
    project_matrix_effect: tuple[ExperimentOut, AnalysisResultOut] | None = None


def _latest_project_matrix_effect(
    session: Session, exp: ExperimentOut
) -> tuple[ExperimentOut, AnalysisResultOut] | None:
    """Most recent matrix-effect result in the project up to this experiment's date."""
    found: tuple[ExperimentOut, AnalysisResultOut] | None = None
    for summary in eln.list_experiments(session, exp.project_id):
        if summary.performed_on > exp.performed_on:
            continue
        res = analysis.latest_results(session, summary.id).get("matrix_effect")
        if res is not None:
            found = (eln.get_experiment(session, summary.id), res)
    return found


def build_context(session: Session, experiment_id: int) -> CritiqueContext:
    """Collect facts about an experiment (vs. its parent) and register evidence."""
    exp = eln.get_experiment(session, experiment_id)
    baseline = (
        eln.get_experiment(session, exp.parent_experiment_id) if exp.parent_experiment_id else None
    )
    metrics = analysis.get_metrics(session, exp.id)
    results = analysis.latest_results(session, exp.id)
    diff = memory.diff(session, baseline.id, exp.id) if baseline else None
    comparison = analysis.compare(session, baseline.id, exp.id) if baseline else None
    book = EvidenceBook()
    ctx = CritiqueContext(
        experiment=exp,
        baseline=baseline,
        diff=diff,
        metrics=metrics,
        comparison=comparison,
        results=results,
        criteria=analysis.get_criteria(),
        evidence=book,
        project_matrix_effect=_latest_project_matrix_effect(session, exp),
    )

    rec = results.get("recovery")
    if rec is not None and metrics.recovery_mean_pct is not None:
        book.add(
            "recovery_mean",
            source="analysis",
            ref_type="analysis.AnalysisResult",
            ref_id=rec.id,
            label=f"{exp.code} 평균 회수율",
            value=metrics.recovery_mean_pct,
            unit="%",
        )
        if metrics.recovery_rsd_pct is not None:
            book.add(
                "recovery_rsd",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{exp.code} 회수율 RSD",
                value=metrics.recovery_rsd_pct,
                unit="%",
            )
        for a in metrics.per_analyte_recovery:
            book.add(
                f"recovery:{a.analyte}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{exp.code} {a.analyte} 회수율",
                value=a.mean_pct,
                unit="%",
            )
    if comparison is not None and baseline is not None:
        base_rec = analysis.latest_results(session, baseline.id).get("recovery")
        if base_rec is not None and comparison.metrics_a.recovery_mean_pct is not None:
            book.add(
                "baseline_recovery_mean",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=base_rec.id,
                label=f"{baseline.code} 평균 회수율",
                value=comparison.metrics_a.recovery_mean_pct,
                unit="%",
            )
        if comparison.recovery_delta_pct_points is not None and rec is not None:
            book.add(
                "recovery_delta",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{baseline.code} 대비 회수율 변화",
                value=comparison.recovery_delta_pct_points,
                unit="%p",
            )
        if comparison.recovery_t_test is not None and rec is not None:
            book.add(
                "recovery_p",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label="Welch t-test p-value",
                value=comparison.recovery_t_test.p_value,
            )
        if rec is not None:
            for d in comparison.per_analyte:
                book.add(
                    f"delta:{d.analyte}",
                    source="analysis",
                    ref_type="analysis.AnalysisResult",
                    ref_id=rec.id,
                    label=f"{d.analyte} 회수율 변화",
                    value=d.delta_pct_points,
                    unit="%p",
                )
    if diff is not None and baseline is not None:
        for c in diff.condition_changes:
            numeric = c.value_b if isinstance(c.value_b, int | float) else None
            book.add(
                f"change:{c.key}",
                source="memory",
                ref_type="eln.Experiment",
                ref_id=exp.id,
                label=f"{c.label} 변경",
                value=numeric,
                text=(
                    f"{c.label}: {baseline.code} {format_value(c.value_a)} → "
                    f"{exp.code} {format_value(c.value_b)}"
                ),
            )
    isr = results.get("is_response")
    if isr is not None and metrics.is_injections_total:
        book.add(
            "is_flagged",
            source="analysis",
            ref_type="analysis.AnalysisResult",
            ref_id=isr.id,
            label="IS 응답 기준 이탈 주입 수",
            value=float(metrics.is_injections_flagged or 0),
            text=f"총 {metrics.is_injections_total}회 주입 중",
        )
        book.add(
            "is_total",
            source="analysis",
            ref_type="analysis.AnalysisResult",
            ref_id=isr.id,
            label="IS 평가 주입 수",
            value=float(metrics.is_injections_total),
        )
    cal = results.get("calibration")
    if cal is not None and isinstance(cal.output, CalibrationOutput):
        if metrics.min_r_squared is not None:
            book.add(
                "min_r2",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=cal.id,
                label="검량선 최소 R²",
                value=metrics.min_r_squared,
            )
        if metrics.max_abs_back_calc_error_pct is not None:
            book.add(
                "max_back_calc",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=cal.id,
                label="역산 정확도 최대 편차",
                value=metrics.max_abs_back_calc_error_pct,
                unit="%",
            )
        for w in cal.output.weighting_comparison:
            book.add(
                f"weighting:{w.weighting}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=cal.id,
                label=f"가중 {w.weighting} Σ|%RE|",
                value=w.sum_abs_relative_error_pct,
                unit="%",
            )
    if ctx.project_matrix_effect is not None:
        me_exp, me_res = ctx.project_matrix_effect
        out = me_res.output
        if out.kind == "matrix_effect":
            for me_item in out.analytes:
                book.add(
                    f"me:{me_item.analyte}",
                    source="analysis",
                    ref_type="analysis.AnalysisResult",
                    ref_id=me_res.id,
                    label=f"{me_exp.code} {me_item.analyte} 매트릭스 효과",
                    value=me_item.matrix_effect_pct,
                    unit="%",
                )
    return ctx


# --------------------------------------------------------------- grounding

_NUMBER = re.compile(r"(?<![#\w.])[-−]?\d+(?:\.\d+)?")
#: Tokens that contain digits but are names, not quantities.
_NAME_TOKENS = ("1/x2", "1/x", "R²")
#: Fixed statistical thresholds that may appear in prose.
_STAT_THRESHOLDS = ("0.05", "0.01", "0.001")


def _allowed_numbers(ctx: CritiqueContext) -> set[str]:
    allowed: set[str] = set()
    for ev in ctx.evidence.items:
        if ev.value is not None:
            v = abs(ev.value)
            for digits in range(0, 4):
                allowed.add(f"{v:.{digits}f}")
            allowed.add(f"{v:g}")
        for text in (ev.label, ev.text or ""):
            allowed.update(m.lstrip("-−") for m in _NUMBER.findall(text))
    for value in ctx.experiment.condition_block.model_dump(exclude_none=True).values():
        allowed.update(m.lstrip("-−") for m in _NUMBER.findall(str(value)))
    c = ctx.criteria
    for v in (
        c.recovery_min_pct,
        c.recovery_max_pct,
        c.rsd_max_pct,
        c.r_squared_min,
        c.back_calc_tolerance_pct,
        c.is_response_min_pct,
        c.is_response_max_pct,
        c.matrix_effect_abs_max_pct,
    ):
        allowed.update({f"{v:g}", f"{v:.0f}", f"{v:.1f}", f"{v:.2f}"})
    allowed.update(m.lstrip("-−") for m in _NUMBER.findall(c.source))
    allowed.update(_STAT_THRESHOLDS)
    return allowed


def ungrounded_numbers(draft: CritiqueDraft, ctx: CritiqueContext) -> list[str]:
    """Numbers in a draft's prose that do not trace to evidence, conditions or criteria."""
    allowed = _allowed_numbers(ctx)
    texts = [draft.summary]
    texts += [f.title + " " + f.body for f in draft.findings]
    texts += [h.statement + " " + h.rationale for h in draft.hypotheses]
    texts += [p.title + " " + p.description for p in draft.proposals]
    bad: list[str] = []
    for text in texts:
        for token in _NAME_TOKENS:
            text = text.replace(token, " ")
        for m in _NUMBER.findall(text):
            if m.lstrip("-−") not in allowed:
                bad.append(m)
    return bad


def unknown_evidence_keys(draft: CritiqueDraft, ctx: CritiqueContext) -> list[str]:
    known = {e.key for e in ctx.evidence.items}
    cited = [k for f in draft.findings for k in f.evidence_keys]
    cited += [k for h in draft.hypotheses for k in h.evidence_keys]
    cited += [k for p in draft.proposals for k in p.evidence_keys]
    return sorted({k for k in cited if k not in known})
