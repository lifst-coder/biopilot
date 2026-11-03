"""Builds the grounded context (facts + evidence list) that every Partner engine consumes.

This is the *only* place Partner reads other modules, and it does so exclusively via
their service interfaces. Every number an engine may mention is materialised here as
an :class:`~app.partner.schemas.Evidence` with a reference to the stored record.
Partner never computes new numbers: it copies values from Analysis results, condition
values from ELN originals, structural changes from the Memory diff, and decisions from
its own ``partner_decisions`` table.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.analysis.schemas import (
    AcceptanceCriteria,
    AnalysisResultOut,
    CalibrationOutput,
    ExperimentMetrics,
    MetricsComparison,
    QCFlag,
    ResultKind,
    TrendPoint,
)
from app.eln import service as eln
from app.eln.schemas import ExperimentOut, ExperimentSummary
from app.memory import service as memory
from app.memory.schemas import ConditionChange, ExperimentDiff
from app.partner.feedback import ACTION_LABEL, DecisionMemory, load_decisions
from app.partner.grounding import GroundingIndex, base_index
from app.partner.knowledge import MATRIX_MATCHED_VALUES, PRETREATMENT_KEYS
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

    def prefixed(self, prefix: str) -> list[Evidence]:
        return [e for name, e in self.by_name.items() if name.startswith(prefix)]


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
    #: Pretreatment differences between the matrix-effect experiment and this one.
    me_protocol_changes: list[ConditionChange] = field(default_factory=list)
    decisions: DecisionMemory = field(default_factory=DecisionMemory)
    project_experiments: list[ExperimentSummary] = field(default_factory=list)

    # ------------------------------------------------------------ derived facts

    @property
    def conditions(self) -> dict[str, object]:
        return dict(self.experiment.condition_block.model_dump(exclude_none=True))

    @property
    def matrix_matched(self) -> bool:
        """Quantified against a matrix-matched curve (condition key ``calibration_type``)."""
        return str(self.conditions.get("calibration_type", "")).lower() in MATRIX_MATCHED_VALUES

    @property
    def post_spike_recorded(self) -> bool:
        """Pre/post-extraction spike data recorded (condition key ``spike_stage``)."""
        return "post" in str(self.conditions.get("spike_stage", "")).lower()

    @property
    def is_stage_recorded(self) -> bool:
        return "is_addition_stage" in self.conditions

    @property
    def me_transferable(self) -> bool:
        """A matrix effect was measured under *this* pretreatment protocol."""
        return self.project_matrix_effect is not None and not self.me_protocol_changes

    @property
    def pretreatment_changes(self) -> list[ConditionChange]:
        changes = self.diff.condition_changes if self.diff else []
        return [c for c in changes if c.key in PRETREATMENT_KEYS]

    def failing_analytes(self) -> list[str]:
        return sorted(
            {
                f.analyte
                for f in self.metrics.flags
                if f.code == "recovery_out_of_range" and f.analyte
            }
        )

    def flags(self, code: str) -> list[QCFlag]:
        return [f for f in self.metrics.flags if f.code == code]

    def code_of(self, experiment_id: int) -> str:
        for e in self.project_experiments:
            if e.id == experiment_id:
                return e.code
        return f"실험 {experiment_id}"

    @property
    def grounding(self) -> GroundingIndex:
        return grounding_index(self)

    def fingerprint(self) -> str:
        """Hash of the grounded inputs (evidence + decisions) — identical inputs reuse."""
        payload = {
            "experiment": self.experiment.id,
            "evidence": [e.model_dump(mode="json", exclude={"key"}) for e in self.evidence.items],
            "decisions": [(d.decision_id, d.action) for d in self.decisions.decisions],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _latest_project_matrix_effect(
    session: Session, exp: ExperimentOut, experiments: list[ExperimentSummary]
) -> tuple[ExperimentOut, AnalysisResultOut] | None:
    """Most recent matrix-effect result in the project up to this experiment's date."""
    found: tuple[ExperimentOut, AnalysisResultOut] | None = None
    for summary in experiments:
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
    experiments = eln.list_experiments(session, exp.project_id)
    metrics = analysis.get_metrics(session, exp.id)
    results = analysis.latest_results(session, exp.id)
    diff = memory.diff(session, baseline.id, exp.id) if baseline else None
    comparison = analysis.compare(session, baseline.id, exp.id) if baseline else None
    project_me = _latest_project_matrix_effect(session, exp, experiments)
    me_changes: list[ConditionChange] = []
    if project_me is not None and project_me[0].id != exp.id:
        me_diff = memory.diff(session, project_me[0].id, exp.id)
        me_changes = [c for c in me_diff.condition_changes if c.key in PRETREATMENT_KEYS]
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
        project_matrix_effect=project_me,
        me_protocol_changes=me_changes,
        decisions=load_decisions(session, exp.project_id),
        project_experiments=experiments,
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
    _register_extended_evidence(session, ctx)
    return ctx


def _register_extended_evidence(session: Session, ctx: CritiqueContext) -> None:
    """Evidence used by the structured Critic / Designer (appended after the core set).

    Appending keeps the keys of the core evidence set stable (``E1``… unchanged).
    """
    book, exp = ctx.evidence, ctx.experiment
    rec = ctx.results.get("recovery")
    # Which spike levels fail, per analyte (from the QC flag context, no arithmetic).
    if rec is not None:
        levels: dict[str, list[str]] = {}
        for f in ctx.flags("recovery_out_of_range"):
            if f.analyte:
                levels.setdefault(f.analyte, []).append(format_value(f.context.get("spike_ng_g")))
        for analyte, lv in sorted(levels.items()):
            book.add(
                f"fail_levels:{analyte}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{exp.code} {analyte} 기준 미달 첨가 수준",
                text=f"{', '.join(lv)} ng/g",
            )
        for f in ctx.flags("recovery_rsd_high"):
            book.add(
                f"rsd_high:{f.analyte}:{format_value(f.context.get('spike_ng_g'))}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{exp.code} {f.analyte} RSD (기준 초과)",
                value=f.value,
                unit="%",
                text=f"첨가 수준 {format_value(f.context.get('spike_ng_g'))} ng/g",
            )
    # Individual IS deviations (sample-specific vs systematic pattern).
    isr = ctx.results.get("is_response")
    if isr is not None:
        for f in ctx.flags("is_suppression") + ctx.flags("is_enhancement"):
            inj = str(f.context.get("injection_id", "?"))
            book.add(
                f"is_injection:{inj}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=isr.id,
                label=f"IS 응답 이탈 {inj}",
                value=f.value,
                unit="%",
                text=f"시료 {f.context.get('sample_id', '?')}",
            )
    # Replicates per level: baseline protocol first (design basis), else this experiment.
    for source_exp in (ctx.baseline, exp):
        if source_exp is None:
            continue
        res = analysis.latest_results(session, source_exp.id).get("recovery")
        if res is not None and res.output.kind == "recovery" and res.output.groups:
            book.add(
                "replicates",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=res.id,
                label=f"{source_exp.code} 첨가 수준당 반복 수",
                value=float(min(g.n for g in res.output.groups)),
            )
            break
    # Quantification + IS records from the original condition block.
    if rec is not None:
        cal_type = ctx.conditions.get("calibration_type")
        book.add(
            "calibration_type",
            source="eln",
            ref_type="eln.Experiment",
            ref_id=exp.id,
            label=f"{exp.code} 정량 검량선 종류",
            text=(
                f"calibration_type = {cal_type}"
                if cal_type
                else "calibration_type 미기록 — 용매 표준 검량선으로 정량"
            ),
        )
        stage = ctx.conditions.get("is_addition_stage")
        book.add(
            "is_addition_stage",
            source="eln",
            ref_type="eln.Experiment",
            ref_id=exp.id,
            label=f"{exp.code} IS 첨가 시점",
            text=f"is_addition_stage = {stage}" if stage else "is_addition_stage 미기록",
        )
    # Matrix-effect protocol transfer (Memory diff of the ME experiment vs this one).
    if ctx.project_matrix_effect is not None:
        me_exp, me_res = ctx.project_matrix_effect
        for c in ctx.me_protocol_changes:
            book.add(
                f"me_protocol:{c.key}",
                source="memory",
                ref_type="eln.Experiment",
                ref_id=exp.id,
                label=f"매트릭스 효과 측정({me_exp.code}) 이후 바뀐 {c.label}",
                text=(
                    f"{c.label}: {me_exp.code} {format_value(c.value_a)} → "
                    f"{exp.code} {format_value(c.value_b)}"
                ),
            )
        for f in me_res.flags:
            if f.code == "matrix_effect_significant" and f.analyte:
                book.add(
                    f"me_significant:{f.analyte}",
                    source="analysis",
                    ref_type="analysis.AnalysisResult",
                    ref_id=me_res.id,
                    label=f"{me_exp.code} {f.analyte} 매트릭스 효과 (기준 초과)",
                    value=f.value,
                    unit="%",
                )
    # Decision History — researcher feedback.
    for d in ctx.decisions.decisions:
        d.evidence = book.add(
            f"decision:{d.decision_id}",
            source="partner",
            ref_type="partner.Decision",
            ref_id=d.decision_id,
            label=f"P{d.proposal_id} {ACTION_LABEL.get(d.action, d.action)} 사유",
            text=d.rationale,
        )


# --------------------------------------------------------------- project scope


@dataclass
class ProjectContext:
    """Facts across all experiments of a project (PAR-7)."""

    project_id: int
    project_name: str
    experiments: list[ExperimentOut]
    trend: list[TrendPoint]
    metrics: dict[int, ExperimentMetrics]
    criteria: AcceptanceCriteria
    evidence: EvidenceBook
    decisions: DecisionMemory

    @property
    def grounding(self) -> GroundingIndex:
        index = base_index()
        for ev in self.evidence.items:
            index.add_value(ev.value, ev.unit)
            index.add_text(ev.label)
            index.add_text(ev.text)
        for e in self.experiments:
            for v in e.condition_block.model_dump(exclude_none=True).values():
                index.add_text(str(v))
        _add_criteria(index, self.criteria)
        return index

    def fingerprint(self) -> str:
        payload = {
            "project": self.project_id,
            "evidence": [e.model_dump(mode="json", exclude={"key"}) for e in self.evidence.items],
            "decisions": [(d.decision_id, d.action) for d in self.decisions.decisions],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build_project_context(session: Session, project_id: int) -> ProjectContext:
    """Per-experiment recovery outcomes + their condition values as evidence."""
    project = eln.get_project(session, project_id)
    experiments = eln.list_experiments_full(session, project_id)
    trend = analysis.project_trend(session, project_id)
    metrics = {e.id: analysis.get_metrics(session, e.id) for e in experiments}
    book = EvidenceBook()
    ctx = ProjectContext(
        project_id=project_id,
        project_name=project.name,
        experiments=experiments,
        trend=trend,
        metrics=metrics,
        criteria=analysis.get_criteria(),
        evidence=book,
        decisions=load_decisions(session, project_id),
    )
    for exp in experiments:
        rec = analysis.latest_results(session, exp.id).get("recovery")
        m = metrics[exp.id]
        if rec is None or m.recovery_mean_pct is None:
            continue
        book.add(
            f"recovery_mean:{exp.code}",
            source="analysis",
            ref_type="analysis.AnalysisResult",
            ref_id=rec.id,
            label=f"{exp.code} 평균 회수율",
            value=m.recovery_mean_pct,
            unit="%",
        )
        failing = sorted(
            {f.analyte for f in m.flags if f.code == "recovery_out_of_range" and f.analyte}
        )
        if failing:
            book.add(
                f"failing:{exp.code}",
                source="analysis",
                ref_type="analysis.AnalysisResult",
                ref_id=rec.id,
                label=f"{exp.code} 기준 미달 분석물",
                text=", ".join(failing),
            )
    for exp in experiments:
        me = analysis.latest_results(session, exp.id).get("matrix_effect")
        if me is None:
            continue
        for f in me.flags:
            if f.code == "matrix_effect_significant" and f.analyte:
                book.add(
                    f"me_significant:{f.analyte}",
                    source="analysis",
                    ref_type="analysis.AnalysisResult",
                    ref_id=me.id,
                    label=f"{exp.code} {f.analyte} 매트릭스 효과 (기준 초과)",
                    value=f.value,
                    unit="%",
                )
    for d in ctx.decisions.decisions:
        d.evidence = book.add(
            f"decision:{d.decision_id}",
            source="partner",
            ref_type="partner.Decision",
            ref_id=d.decision_id,
            label=f"P{d.proposal_id} {ACTION_LABEL.get(d.action, d.action)} 사유",
            text=d.rationale,
        )
    return ctx


def condition_evidence(ctx: ProjectContext, exp: ExperimentOut, key: str, label: str) -> Evidence:
    """Register (once) an ELN evidence item for one experiment's condition value."""
    name = f"condition:{exp.code}:{key}"
    existing = ctx.evidence.get(name)
    if existing is not None:
        return existing
    value = exp.condition_block.model_dump().get(key)
    return ctx.evidence.add(
        name,
        source="eln",
        ref_type="eln.Experiment",
        ref_id=exp.id,
        label=f"{exp.code} {label}",
        text=f"{label} = {format_value(value)}",
    )


# --------------------------------------------------------------- grounding


def _add_criteria(index: GroundingIndex, c: AcceptanceCriteria) -> None:
    index.add_free(
        [
            c.recovery_min_pct,
            c.recovery_max_pct,
            c.rsd_max_pct,
            c.r_squared_min,
            c.back_calc_tolerance_pct,
            c.is_response_min_pct,
            c.is_response_max_pct,
            c.matrix_effect_abs_max_pct,
        ]
    )
    index.add_text(c.source)


def grounding_index(ctx: CritiqueContext) -> GroundingIndex:
    """Allowed values: evidence (value+unit), labels/texts, conditions, criteria."""
    index = base_index()
    for ev in ctx.evidence.items:
        index.add_value(ev.value, ev.unit)
        index.add_text(ev.label)
        index.add_text(ev.text)
    for exp in (ctx.experiment, ctx.baseline):
        if exp is not None:
            for value in exp.condition_block.model_dump(exclude_none=True).values():
                index.add_text(str(value))
    _add_criteria(index, ctx.criteria)
    return index


def draft_texts(draft: CritiqueDraft) -> list[str]:
    """Every prose field of a draft (the grounding guard scans all of them)."""
    texts = [draft.summary]
    texts += [f.title + " " + f.body for f in draft.findings]
    texts += [h.statement + " " + h.rationale for h in draft.hypotheses]
    for p in draft.proposals:
        texts.append(p.title + " " + p.description)
        if p.design is not None:
            d = p.design
            texts += [d.objective, d.power_rationale, d.replicates_basis or ""]
            texts += [v.label for v in d.variables]
            texts += [c.name + " " + c.purpose for c in d.controls]
            texts += d.measurements
            texts += [o.observation + " " + o.interpretation for o in d.expected_outcomes]
    for a in draft.assessments:
        texts += [a.question, a.claim, a.verdict_reason]
        args = a.supporting_evidence + a.opposing_evidence + a.undetermined_reasons
        for alt in a.alternative_explanations:
            texts += [alt.label, alt.mechanism]
            args = args + alt.supporting + alt.opposing
        texts += [arg.statement for arg in args]
        texts += [
            m.name + " " + m.purpose + " " + (m.decision_note or "") for m in a.missing_controls
        ]
    texts += [f.note for f in draft.decision_feedback]
    return texts


def ungrounded_numbers(draft: CritiqueDraft, ctx: CritiqueContext | ProjectContext) -> list[str]:
    """Numbers in a draft's prose that do not trace to evidence, conditions or criteria."""
    index = ctx.grounding
    bad = index.ungrounded(draft_texts(draft))
    for p in draft.proposals:
        reps = p.design.replicates if p.design else None
        if reps is not None and not index.grounds(float(reps)):
            bad.append(str(reps))
    return bad


def _cited_keys(draft: CritiqueDraft) -> list[str]:
    cited = [k for f in draft.findings for k in f.evidence_keys]
    cited += [k for h in draft.hypotheses for k in h.evidence_keys]
    cited += [k for p in draft.proposals for k in p.evidence_keys]
    cited += [
        p.design.replicates_evidence_key
        for p in draft.proposals
        if p.design and p.design.replicates_evidence_key
    ]
    for a in draft.assessments:
        args = a.supporting_evidence + a.opposing_evidence + a.undetermined_reasons
        for alt in a.alternative_explanations:
            args = args + alt.supporting + alt.opposing
        cited += [k for arg in args for k in arg.evidence_keys]
        cited += [k for m in a.missing_controls for k in m.evidence_keys]
    cited += [f.evidence_key for f in draft.decision_feedback if f.evidence_key]
    return cited


def unknown_evidence_keys(draft: CritiqueDraft, ctx: CritiqueContext | ProjectContext) -> list[str]:
    known = {e.key for e in ctx.evidence.items}
    return sorted({k for k in _cited_keys(draft) if k not in known})
