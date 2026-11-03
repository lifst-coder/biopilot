"""Deterministic, offline critique engine (default mode).

Every sentence is built from evidence values registered in the context, so the
output is reproducible and fully grounded. Domain heuristics are explicit tables
below so that they can be reviewed and extended (see TASKS.md, Partner).
"""

from __future__ import annotations

from app.partner.context import CritiqueContext, format_value
from app.partner.schemas import (
    CritiqueDraft,
    Evidence,
    Finding,
    HypothesisDraft,
    ProposalChange,
    ProposalDraft,
)

#: Condition keys whose change plausibly affects *extraction recovery*, with the
#: mechanism stated as a hypothesis template.
RECOVERY_MECHANISMS: dict[str, str] = {
    "extraction_time_min": "추출 시간 변경이 분배 평형 도달에 영향을 주어 추출 효율이 달라졌다",
    "cleanup_sorbent": "d-SPE 흡착제 변경으로 일부 분석물이 정제 단계에서 흡착·손실되었다",
    "ph": "pH 변경으로 pH 의존성 분석물의 안정성/분배가 달라졌다",
    "buffer": "완충염 변경으로 추출 pH가 달라져 분배가 영향을 받았다",
    "extraction_solvent": "추출 용매 변경으로 분석물 용해도/분배가 달라졌다",
    "sample_mass_g": "시료량 변경으로 시료/용매 비가 달라졌다",
}

#: Sorbent-specific knowledge (substring match on the new sorbent description).
SORBENT_NOTES: dict[str, str] = {
    "GCB": (
        "GCB(흑연화 카본)는 평면 구조 분석물(예: 벤즈이미다졸계)을 강하게 흡착하는 것으로 "
        "알려져 있다"
    ),
}

PLANAR_ANALYTES: frozenset[str] = frozenset({"carbendazim", "thiabendazole"})

#: Switching calibration weighting is only suggested when the alternative lowers the
#: summed back-calculation error by at least this fraction (avoids chasing noise).
WEIGHTING_MIN_RELATIVE_GAIN = 0.20


def _fmt_p(p: float) -> str:
    """p-value text using only evidence-traceable digits or fixed thresholds."""
    if p < 0.001:
        return "p<0.001"
    return f"p={p:.3f}"


def _calibration_is_replicated(ctx: CritiqueContext) -> bool:
    cal = ctx.results.get("calibration")
    if cal is None or cal.output.kind != "calibration":
        return False
    return all(a.n >= 2 * len(a.back_calc) for a in cal.output.analytes)


def _fmt(ev: Evidence | None, digits: int = 1) -> str:
    if ev is None or ev.value is None:
        return "—"
    unit = ev.unit or ""
    return f"{ev.value:.{digits}f}{unit}"


class RulesCritiqueEngine:
    """Rule-based critique: QC criteria, confounded changes, IS suppression, calibration."""

    name = "rules"

    def critique(self, ctx: CritiqueContext) -> CritiqueDraft:
        ev = ctx.evidence
        c = ctx.criteria
        exp = ctx.experiment
        findings: list[Finding] = []
        hypotheses: list[HypothesisDraft] = []
        proposals: list[ProposalDraft] = []

        # 1. Recovery acceptance --------------------------------------------------
        out_of_range = sorted(
            {
                f.analyte
                for f in ctx.metrics.flags
                if f.code == "recovery_out_of_range" and f.analyte
            }
        )
        if out_of_range:
            keys = [k.key for a in out_of_range if (k := ev.get(f"recovery:{a}"))]
            details = ", ".join(f"{a} {_fmt(ev.get(f'recovery:{a}'))}" for a in out_of_range)
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

        # 2. Significant change vs baseline --------------------------------------
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
                        f"평균 회수율 {_fmt(base_mean)} → {_fmt(mean)} "
                        f"(변화 {_fmt(delta)}, Welch t-test {_fmt_p(p.value)})."
                    ),
                    severity="warning" if significant else "info",
                    evidence_keys=[e.key for e in (base_mean, mean, delta, p) if e],
                )
            )

        # 3. Confounded design: several conditions changed at once ---------------
        changes = ctx.diff.condition_changes if ctx.diff else []
        change_evs = [e for ch in changes if (e := ev.get(f"change:{ch.key}"))]
        dropped = bool(delta and delta.value is not None and delta.value < 0)
        if ctx.baseline and len(changes) > 1:
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

        # 4. Hypotheses per plausible mechanism ----------------------------------
        hyp_index: dict[str, int] = {}
        if ctx.baseline and dropped:
            for ch in changes:
                template = RECOVERY_MECHANISMS.get(ch.key)
                change_ev = ev.get(f"change:{ch.key}")
                if template is None or change_ev is None:
                    continue
                rationale = f"{change_ev.text}."
                cited = [change_ev.key] + ([delta.key] if delta else [])
                if ch.key == "cleanup_sorbent":
                    for token, note in SORBENT_NOTES.items():
                        if token in str(ch.value_b) and token not in str(ch.value_a):
                            planar = [
                                d for a in sorted(PLANAR_ANALYTES) if (d := ev.get(f"delta:{a}"))
                            ]
                            rationale += f" {note}."
                            if planar:
                                rationale += (
                                    " 해당 분석물 변화: "
                                    + ", ".join(f"{d.label} {_fmt(d)}" for d in planar)
                                    + "."
                                )
                                cited += [d.key for d in planar]
                hyp_index[ch.key] = len(hypotheses)
                hypotheses.append(
                    HypothesisDraft(statement=template, rationale=rationale, evidence_keys=cited)
                )

        # 5. IS response -----------------------------------------------------------
        is_flagged, is_total = ev.get("is_flagged"), ev.get("is_total")
        if is_flagged and is_flagged.value and is_total:
            me_evs = [e for name, e in ev.by_name.items() if name.startswith("me:")]
            body = (
                f"IS 응답이 기준({c.is_response_min_pct:g}–{c.is_response_max_pct:g}%)을 벗어난 "
                f"주입이 {is_flagged.value:.0f}/{is_total.value:.0f}회 있다. IS 보정이 "
                "매트릭스 억제를 완전히 상쇄한다는 가정을 해당 시료에서 검증해야 한다."
            )
            if me_evs:
                worst = min(me_evs, key=lambda e: e.value if e.value is not None else 0.0)
                body += f" 프로젝트 기록상 가장 큰 매트릭스 효과: {worst.label} {_fmt(worst)}."
            findings.append(
                Finding(
                    title="내부표준(IS) 응답 억제",
                    body=body,
                    severity="warning",
                    evidence_keys=[is_flagged.key, is_total.key] + [e.key for e in me_evs],
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
            proposals.append(
                ProposalDraft(
                    title="IS 억제 시료 재분석 (희석 주입 + 매트릭스 매칭 검량선)",
                    description=(
                        "IS 기준 이탈 시료를 희석 재주입하고 매트릭스 매칭 검량선으로 정량해 "
                        "억제 영향을 분리한다. 희석 배율은 연구자가 정한다."
                    ),
                    changes=[
                        ProposalChange(key="injection_dilution", value="researcher-defined"),
                        ProposalChange(key="calibration_type", value="matrix-matched"),
                    ],
                    evidence_keys=[is_flagged.key],
                    hypothesis_index=hyp_index["__matrix__"],
                )
            )

        # 6. Single-variable follow-ups for confounded changes ---------------------
        if ctx.baseline and len(changes) > 1 and dropped:
            for ch in changes:
                if ch.key not in RECOVERY_MECHANISMS:
                    continue
                change_ev = ev.get(f"change:{ch.key}")
                proposals.append(
                    ProposalDraft(
                        title=f"단일 변수 실험: {ch.label}만 변경",
                        description=(
                            f"{ctx.baseline.code} 기준 프로토콜에서 {ch.label}만 "
                            f"{format_value(ch.value_b)}(으)로 바꾸고 나머지는 유지해 "
                            "영향을 분리한다."
                        ),
                        changes=[ProposalChange(key=ch.key, value=ch.value_b)],
                        evidence_keys=[change_ev.key] if change_ev else [],
                        hypothesis_index=hyp_index.get(ch.key),
                    )
                )

        # 7. Calibration -----------------------------------------------------------
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
                    body=f"최대 편차 {_fmt(back)} > ±{c.back_calc_tolerance_pct:g}%.",
                    severity="warning",
                    evidence_keys=[back.key],
                )
            )
        weights = {w: e for w in ("none", "1/x", "1/x2") if (e := ev.get(f"weighting:{w}"))}
        if not _calibration_is_replicated(ctx):
            weights = {}  # weighting choice needs replicate injections per level
        used = exp.condition_block.calibration_weighting or "none"
        if weights and used in weights:
            best = min(weights, key=lambda w: weights[w].value or 0.0)
            used_err = weights[used].value or 0.0
            best_err = weights[best].value or 0.0
            gain = (used_err - best_err) / used_err if used_err > 0 else 0.0
            if best != used and gain >= WEIGHTING_MIN_RELATIVE_GAIN:
                findings.append(
                    Finding(
                        title=f"가중 {best}가 역산 오차를 더 줄임",
                        body=(
                            f"현재 가중 {used} Σ|%RE| {_fmt(weights[used])} 대비 "
                            f"{best} {_fmt(weights[best])}."
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
                    )
                )
            elif "recovery" not in ctx.results:  # calibration-focused experiment
                findings.append(
                    Finding(
                        title=f"가중 {used} 선택이 데이터와 일치",
                        body="현재 가중보다 역산 오차 합(Σ|%RE|)을 의미 있게 줄이는 가중이 "
                        "없다: " + ", ".join(f"{w} {_fmt(e)}" for w, e in weights.items()) + ".",
                        severity="info",
                        evidence_keys=[e.key for e in weights.values()],
                    )
                )

        # 8. Nothing analysed / all clear ------------------------------------------
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
            findings.append(
                Finding(
                    title="허용 기준 충족",
                    body=f"저장된 결과에서 {c.source} 기준 위반이 발견되지 않았다.",
                    severity="info",
                    evidence_keys=[e.key for e in (mean,) if e],
                )
            )

        order = {"critical": 0, "warning": 1, "info": 2}
        top = min(findings, key=lambda f: order[f.severity])
        summary = f"{exp.code} 비판적 검토 — 가장 중요한 지적: {top.title}."
        return CritiqueDraft(
            summary=summary, findings=findings, hypotheses=hypotheses, proposals=proposals
        )
