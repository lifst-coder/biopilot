"""Deterministic, offline critique engine (default mode).

Every sentence is built from evidence values registered in the context, so the
output is reproducible and fully grounded. Domain heuristics live in explicit tables
(:mod:`app.partner.knowledge`) so they can be reviewed and extended. The engine
composes three parts that share one :class:`CritiqueDraft`:

1. **findings** — QC criteria, confounded changes, IS pattern, calibration and the
   PAR-5 table rules (RSD, matrix effect vs. solvent calibration, pH-sensitive analytes);
2. **Research Critic** — :func:`app.partner.engines.critic.assess_recovery_cause`;
3. **Next Experiment Designer** — :func:`app.partner.engines.designer.design_next_experiments`,
   filtered by the Decision History.
"""

from __future__ import annotations

from app.partner.context import CritiqueContext
from app.partner.engines.critic import assess_recovery_cause, fmt, fmt_p, gcb_introduced
from app.partner.engines.designer import design_next_experiments
from app.partner.knowledge import (
    PH_SENSITIVE_ANALYTES,
    PLANAR_ANALYTES,
    RECOVERY_MECHANISMS,
    SORBENT_NOTES,
)
from app.partner.schemas import (
    CriticAssessment,
    CritiqueDraft,
    ExperimentDesign,
    Finding,
    HypothesisDraft,
    ProposalChange,
    ProposalDraft,
)

#: Switching calibration weighting is only suggested when the alternative lowers the
#: summed back-calculation error by at least this fraction (avoids chasing noise).
WEIGHTING_MIN_RELATIVE_GAIN = 0.20

__all__ = [
    "PLANAR_ANALYTES",
    "RECOVERY_MECHANISMS",
    "SORBENT_NOTES",
    "WEIGHTING_MIN_RELATIVE_GAIN",
    "RulesCritiqueEngine",
]


def _calibration_is_replicated(ctx: CritiqueContext) -> bool:
    cal = ctx.results.get("calibration")
    if cal is None or cal.output.kind != "calibration":
        return False
    return all(a.n >= 2 * len(a.back_calc) for a in cal.output.analytes)


class RulesCritiqueEngine:
    """Rule-based critique: QC criteria, confounds, IS pattern, critic, designer."""

    name = "rules"

    def critique(self, ctx: CritiqueContext) -> CritiqueDraft:
        findings: list[Finding] = []
        hypotheses: list[HypothesisDraft] = []
        proposals: list[ProposalDraft] = []
        hyp_index: dict[str, int] = {}

        self._recovery_findings(ctx, findings)
        assessment = assess_recovery_cause(ctx)
        if assessment is not None:
            findings.append(self._verdict_finding(assessment))
        self._mechanism_hypotheses(ctx, hypotheses, hyp_index)
        self._is_rules(ctx, findings, hypotheses, hyp_index)
        self._table_rules(ctx, findings)
        self._calibration_rules(ctx, findings, proposals)

        designed = design_next_experiments(ctx, assessment, hyp_index)
        proposals = designed.proposals + proposals
        if designed.feedback:
            findings.append(
                Finding(
                    title="이전 연구자 결정 반영",
                    body=" ".join(f.note for f in designed.feedback),
                    severity="info",
                    evidence_keys=[f.evidence_key for f in designed.feedback if f.evidence_key],
                )
            )

        if not ctx.metrics.analyzed:
            findings.append(
                Finding(
                    title="분석 결과 없음",
                    body="저장된 분석 결과가 없어 비판할 수치가 없다. 먼저 분석을 실행하라.",
                    severity="info",
                    evidence_keys=[],
                )
            )
        elif not findings:
            mean = ctx.evidence.get("recovery_mean")
            findings.append(
                Finding(
                    title="허용 기준 충족",
                    body=f"저장된 결과에서 {ctx.criteria.source} 기준 위반이 발견되지 않았다.",
                    severity="info",
                    evidence_keys=[e.key for e in (mean,) if e],
                )
            )

        order = {"critical": 0, "warning": 1, "info": 2}
        top = min(findings, key=lambda f: order[f.severity])
        summary = f"{ctx.experiment.code} 비판적 검토 — 가장 중요한 지적: {top.title}."
        if assessment is not None:
            summary += f" 판정: {assessment.verdict_reason}"
        return CritiqueDraft(
            summary=summary,
            findings=findings,
            hypotheses=hypotheses,
            proposals=proposals,
            assessments=[assessment] if assessment else [],
            decision_feedback=designed.feedback,
        )

    # ------------------------------------------------------------ findings

    @staticmethod
    def _recovery_findings(ctx: CritiqueContext, findings: list[Finding]) -> None:
        ev, c = ctx.evidence, ctx.criteria
        out_of_range = ctx.failing_analytes()
        if out_of_range:
            keys = [k.key for a in out_of_range if (k := ev.get(f"recovery:{a}"))]
            details = ", ".join(f"{a} {fmt(ev.get(f'recovery:{a}'))}" for a in out_of_range)
            findings.append(
                Finding(
                    title="회수율 허용 범위 이탈",
                    body=(
                        f"허용 범위({c.recovery_min_pct:g}–{c.recovery_max_pct:g}%, {c.source})를 "
                        f"벗어난 분석물: {details}."
                    ),
                    severity="critical",
                    evidence_keys=keys,
                )
            )
        delta, p = ev.get("recovery_delta"), ev.get("recovery_p")
        base_mean, mean = ev.get("baseline_recovery_mean"), ev.get("recovery_mean")
        if ctx.baseline and delta and delta.value is not None and p and p.value is not None:
            significant = p.value < 0.05
            direction = "저하" if delta.value < 0 else "상승"
            findings.append(
                Finding(
                    title=f"{ctx.baseline.code} 대비 회수율 {direction}"
                    + (" (통계적으로 유의)" if significant else " (유의하지 않음)"),
                    body=(
                        f"평균 회수율 {fmt(base_mean)} → {fmt(mean)} "
                        f"(변화 {fmt(delta)}, Welch t-test {fmt_p(p.value)})."
                    ),
                    severity="warning" if significant else "info",
                    evidence_keys=[e.key for e in (base_mean, mean, delta, p) if e],
                )
            )
        changes = ctx.diff.condition_changes if ctx.diff else []
        if ctx.baseline and len(changes) > 1:
            change_evs = [e for ch in changes if (e := ev.get(f"change:{ch.key}"))]
            labels = ", ".join(ch.label for ch in changes)
            findings.append(
                Finding(
                    title="복수 조건 동시 변경 — 원인 분리 불가",
                    body=(
                        f"{ctx.baseline.code} 대비 여러 조건({labels})이 동시에 바뀌어, "
                        "관찰된 차이를 특정 조건에 귀속할 수 없다. "
                        "단일 변수 실험으로 분리해야 한다."
                    ),
                    severity="warning",
                    evidence_keys=[e.key for e in change_evs],
                )
            )

    @staticmethod
    def _verdict_finding(a: CriticAssessment) -> Finding:
        keys = sorted({k for m in a.missing_controls for k in m.evidence_keys})
        title = {
            "indeterminate": "전처리 손실 vs 매트릭스 효과 — 현재 데이터로 구분 불가",
            "supported": "회수율 저하는 전처리 손실로 해석 가능",
            "refuted": "전처리 손실 가설 반박",
            "no_issue": "원인 분석 불필요",
        }[a.verdict]
        missing = ", ".join(m.name for m in a.missing_controls)
        return Finding(
            title=title,
            body=a.verdict_reason + (f" 누락 대조군: {missing}." if missing else ""),
            severity="warning" if a.verdict == "indeterminate" else "info",
            evidence_keys=keys,
        )

    @staticmethod
    def _mechanism_hypotheses(
        ctx: CritiqueContext, hypotheses: list[HypothesisDraft], hyp_index: dict[str, int]
    ) -> None:
        ev = ctx.evidence
        delta = ev.get("recovery_delta")
        dropped = bool(delta and delta.value is not None and delta.value < 0)
        if not (ctx.baseline and dropped):
            return
        for ch in ctx.diff.condition_changes if ctx.diff else []:
            template = RECOVERY_MECHANISMS.get(ch.key)
            change_ev = ev.get(f"change:{ch.key}")
            if template is None or change_ev is None:
                continue
            rationale = f"{change_ev.text}."
            cited = [change_ev.key] + ([delta.key] if delta else [])
            if ch.key == "cleanup_sorbent" and (token := gcb_introduced(ctx)):
                planar = [d for a in sorted(PLANAR_ANALYTES) if (d := ev.get(f"delta:{a}"))]
                rationale += f" {SORBENT_NOTES[token]}."
                if planar:
                    rationale += (
                        " 해당 분석물 변화: "
                        + ", ".join(f"{d.label} {fmt(d)}" for d in planar)
                        + "."
                    )
                    cited += [d.key for d in planar]
            hyp_index[ch.key] = len(hypotheses)
            hypotheses.append(
                HypothesisDraft(statement=template, rationale=rationale, evidence_keys=cited)
            )

    @staticmethod
    def _is_rules(
        ctx: CritiqueContext,
        findings: list[Finding],
        hypotheses: list[HypothesisDraft],
        hyp_index: dict[str, int],
    ) -> None:
        ev, c = ctx.evidence, ctx.criteria
        is_flagged, is_total = ev.get("is_flagged"), ev.get("is_total")
        if not (is_flagged and is_flagged.value and is_total and is_total.value):
            return
        me_evs = ev.prefixed("me:")
        injections = ev.prefixed("is_injection:")
        body = (
            f"IS 응답이 기준({c.is_response_min_pct:g}–{c.is_response_max_pct:g}%)을 벗어난 "
            f"주입이 {is_flagged.value:.0f}/{is_total.value:.0f}회 있다. IS 보정이 "
            "매트릭스 억제를 완전히 상쇄한다는 가정을 해당 시료에서 검증해야 한다."
        )
        if is_flagged.value < is_total.value:
            ids = ", ".join(f"{e.label.rsplit(' ', 1)[1]}({e.text})" for e in injections)
            body += (
                f" 이탈은 일부 주입({ids})에 한정된 시료 특이적 패턴으로, 체계적인 IS 첨가 "
                "오류보다 시료별 매트릭스 부하 차이를 시사한다."
            )
        else:
            body += (
                " 모든 주입에서 이탈해 IS 첨가 오류·장비 감도 저하 같은 체계적 원인을 먼저 "
                "확인해야 한다."
            )
        if me_evs:
            worst = min(me_evs, key=lambda e: e.value if e.value is not None else 0.0)
            body += f" 프로젝트 기록상 가장 큰 매트릭스 효과: {worst.label} {fmt(worst)}."
        findings.append(
            Finding(
                title="내부표준(IS) 응답 억제",
                body=body,
                severity="warning",
                evidence_keys=[is_flagged.key, is_total.key]
                + [e.key for e in injections]
                + [e.key for e in me_evs],
            )
        )
        hyp_index["__matrix__"] = len(hypotheses)
        hypotheses.append(
            HypothesisDraft(
                statement="일부 시료에서 매트릭스 성분이 이온화를 억제해 IS 응답이 낮아졌다",
                rationale="IS 응답 기준 이탈 주입이 관찰되었다.",
                evidence_keys=[is_flagged.key, *[e.key for e in me_evs]],
            )
        )

    @staticmethod
    def _table_rules(ctx: CritiqueContext, findings: list[Finding]) -> None:
        """PAR-5: RSD, ME-significant analyte on solvent curve, pH-sensitive analytes."""
        ev, c = ctx.evidence, ctx.criteria
        rsd = ev.prefixed("rsd_high:")
        if rsd:
            findings.append(
                Finding(
                    title="회수율 반복성(RSD) 기준 초과",
                    body=(
                        f"RSD 기준(≤{c.rsd_max_pct:g}%)을 넘는 그룹: "
                        + ", ".join(f"{e.label.split(' ')[1]} {e.text} {fmt(e)}" for e in rsd)
                        + ". 평균 회수율 해석 전에 반복 간 변동 원인(균질화·첨가 절차)을 확인해야 "
                        "한다."
                    ),
                    severity="warning",
                    evidence_keys=[e.key for e in rsd],
                )
            )
        me_sig = ev.prefixed("me_significant:")
        own_me = ctx.results.get("matrix_effect")
        if own_me is not None and me_sig:
            findings.append(
                Finding(
                    title="매트릭스 효과 기준 초과 분석물",
                    body=(
                        f"매트릭스 효과가 기준(±{c.matrix_effect_abs_max_pct:g}%)을 넘는 분석물: "
                        + ", ".join(f"{e.label.split(' ')[1]} {fmt(e)}" for e in me_sig)
                        + ". 이 분석물은 매트릭스 매칭 검량선 없이 정량하면 회수율이 억제만큼 "
                        "낮게 보인다. 이 측정은 현재 전처리 조건에서만 유효하다."
                    ),
                    severity="warning",
                    evidence_keys=[e.key for e in me_sig],
                )
            )
        cal_ev = ev.get("calibration_type")
        if me_sig and cal_ev and not ctx.matrix_matched and "recovery" in ctx.results:
            parts, keys = [], [cal_ev.key]
            for e in me_sig:
                analyte = e.label.split(" ")[1]
                rec = ev.get(f"recovery:{analyte}")
                parts.append(
                    f"{analyte} 매트릭스 효과 {fmt(e)}"
                    + (f" (이 실험 회수율 {fmt(rec)})" if rec else "")
                )
                keys += [e.key] + ([rec.key] if rec else [])
            findings.append(
                Finding(
                    title="매트릭스 효과 유의 분석물을 용매 검량선으로 정량",
                    body=(
                        f"매트릭스 효과가 기준(±{c.matrix_effect_abs_max_pct:g}%)을 넘는 분석물("
                        + ", ".join(parts)
                        + ")을 용매 표준 검량선으로 정량했다. 회수율에 이온화 억제가 보정되지 않은 "
                        "채 섞여 있을 수 있어 매트릭스 매칭 검량선이 필요하다."
                    ),
                    severity="warning",
                    evidence_keys=keys,
                )
            )
        changed = {ch.key for ch in ctx.pretreatment_changes}
        if changed & {"ph", "buffer"}:
            items = [
                (a, reason, d)
                for a, reason in PH_SENSITIVE_ANALYTES.items()
                if (d := ev.get(f"delta:{a}"))
            ]
            if items:
                change_keys = [ce.key for k in ("ph", "buffer") if (ce := ev.get(f"change:{k}"))]
                failing = set(ctx.failing_analytes())
                findings.append(
                    Finding(
                        title="pH 민감 분석물 영향 점검",
                        body=(
                            "추출 pH/완충 조건이 바뀌었다. pH 민감 분석물 변화: "
                            + "; ".join(f"{a} {fmt(d)} — {reason}" for a, reason, d in items)
                            + "."
                        ),
                        severity="warning" if failing & {a for a, _r, _d in items} else "info",
                        evidence_keys=change_keys + [d.key for _a, _r, d in items],
                    )
                )

    @staticmethod
    def _calibration_rules(
        ctx: CritiqueContext, findings: list[Finding], proposals: list[ProposalDraft]
    ) -> None:
        ev, c, exp = ctx.evidence, ctx.criteria, ctx.experiment
        r2, back = ev.get("min_r2"), ev.get("max_back_calc")
        if r2 and r2.value is not None and r2.value < c.r_squared_min:
            findings.append(
                Finding(
                    title="검량선 직선성 미흡",
                    body=f"최소 R² {r2.value:.4f} < 기준 {c.r_squared_min:g}.",
                    severity="warning",
                    evidence_keys=[r2.key],
                )
            )
        if back and back.value is not None and back.value > c.back_calc_tolerance_pct:
            findings.append(
                Finding(
                    title="검량선 역산 정확도 기준 초과",
                    body=f"최대 편차 {fmt(back)} > ±{c.back_calc_tolerance_pct:g}%.",
                    severity="warning",
                    evidence_keys=[back.key],
                )
            )
        weights = {w: e for w in ("none", "1/x", "1/x2") if (e := ev.get(f"weighting:{w}"))}
        if not _calibration_is_replicated(ctx):
            weights = {}  # weighting choice needs replicate injections per level
        used = exp.condition_block.calibration_weighting or "none"
        if not (weights and used in weights):
            return
        best = min(weights, key=lambda w: weights[w].value or 0.0)
        used_err = weights[used].value or 0.0
        best_err = weights[best].value or 0.0
        gain = (used_err - best_err) / used_err if used_err > 0 else 0.0
        if best != used and gain >= WEIGHTING_MIN_RELATIVE_GAIN:
            findings.append(
                Finding(
                    title=f"가중 {best}가 역산 오차를 더 줄임",
                    body=(
                        f"현재 가중 {used} Σ|%RE| {fmt(weights[used])} 대비 "
                        f"{best} {fmt(weights[best])}."
                    ),
                    severity="info",
                    evidence_keys=[weights[used].key, weights[best].key],
                )
            )
            proposals.append(
                ProposalDraft(
                    title=f"검량선 가중을 {best}로 변경",
                    description="동일 데이터에서 역산 오차 합이 가장 작은 가중을 사용한다.",
                    changes=[ProposalChange(key="calibration_weighting", value=best)],
                    evidence_keys=[weights[used].key, weights[best].key],
                    design=ExperimentDesign(
                        template_id="calibration_weighting",
                        objective="같은 검량 데이터에서 가중 방식을 바꿔 역산 정확도를 비교한다.",
                        measurements=["가중별 Σ|%RE| — Analysis 계층 계산"],
                        discriminating_power="low",
                        power_rationale="데이터 처리 변경이라 새 측정 없이 확인 가능하다.",
                        basis_experiment_ids=[exp.id],
                    ),
                    base_experiment_id=exp.id,
                )
            )
        elif "recovery" not in ctx.results:  # calibration-focused experiment
            findings.append(
                Finding(
                    title=f"가중 {used} 선택이 데이터와 일치",
                    body="현재 가중보다 역산 오차 합(Σ|%RE|)을 의미 있게 줄이는 가중이 "
                    "없다: " + ", ".join(f"{w} {fmt(e)}" for w, e in weights.items()) + ".",
                    severity="info",
                    evidence_keys=[e.key for e in weights.values()],
                )
            )
