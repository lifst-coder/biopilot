"""Research Critic (rules mode): structured assessment of *why* recovery is low.

Input: the grounded context — Memory diff (what changed vs. the parent and vs. the
matrix-effect experiment), Analysis results (recovery, IS response, matrix effect)
and the Decision History. Output: :class:`~app.partner.schemas.CriticAssessment` with
지지 근거 / 반대 근거 / 누락 대조군 / 대안 설명 / 현재 데이터로 확정 불가한 이유.

Domain rules applied (tables in :mod:`app.partner.knowledge`):

* **매트릭스 효과 vs 추출 손실** — recovery quantified against a *solvent* curve is an
  apparent recovery: extraction loss and ionisation suppression are multiplied
  together and cannot be separated from it alone.
* **전·후 첨가 비교** — only a pre- vs post-extraction spike under the *same*
  protocol separates the two; a matrix effect measured under another pretreatment
  (Memory diff of the ME experiment vs. this one) does not transfer.
* **매트릭스 매칭 검량선** — quantifying against a matrix-matched curve removes the
  ionisation term, so recovery then reflects extraction efficiency.
* **IS 억제 패턴** — IS deviations in a *subset* of injections indicate sample-specific
  suppression; if recovery fails at every spike level, IS correction failure alone
  cannot explain it.
* **GCB 평면 분석물 흡착** — a larger drop of planar analytes after introducing GCB is
  the signature of clean-up adsorption.
"""

from __future__ import annotations

from app.partner.context import CritiqueContext, format_value
from app.partner.feedback import ACTION_LABEL, PriorDecision
from app.partner.knowledge import (
    CONTROLS,
    EXPLANATION_FOR_KEY,
    EXPLANATIONS,
    PLANAR_ANALYTES,
    SORBENT_NOTES,
)
from app.partner.schemas import (
    AlternativeExplanation,
    CriticArgument,
    CriticAssessment,
    Evidence,
    MissingControl,
)


def fmt(ev: Evidence | None, digits: int = 1) -> str:
    """Evidence value as text, rounded for display only (never re-computed)."""
    if ev is None or ev.value is None:
        return "—"
    return f"{ev.value:.{digits}f}{ev.unit or ''}"


def fmt_p(p: float) -> str:
    """p-value text using only evidence-traceable digits or fixed thresholds."""
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def _keys(*evs: Evidence | None) -> list[str]:
    return [e.key for e in evs if e is not None]


def gcb_introduced(ctx: CritiqueContext) -> str | None:
    """Return the sorbent token newly introduced vs. the baseline (e.g. ``"GCB"``)."""
    for ch in ctx.pretreatment_changes:
        if ch.key != "cleanup_sorbent":
            continue
        for token in SORBENT_NOTES:
            if token in str(ch.value_b) and token not in str(ch.value_a):
                return token
    return None


def planar_pattern(ctx: CritiqueContext) -> tuple[list[Evidence], list[Evidence]] | None:
    """Planar vs. other analyte deltas when every planar drop exceeds every other drop."""
    deltas = ctx.evidence.prefixed("delta:")
    planar = [d for d in deltas if d.label.split(" ")[0] in PLANAR_ANALYTES]
    others = [d for d in deltas if d.label.split(" ")[0] not in PLANAR_ANALYTES]
    if not planar or not others:
        return None
    worst_other = min(o.value or 0.0 for o in others)
    if all((p.value or 0.0) < worst_other for p in planar):
        return planar, others
    return None


def decision_note(decisions: list[PriorDecision]) -> tuple[str | None, list[str]]:
    """Summarise recorded decisions on a control (with their evidence keys)."""
    if not decisions:
        return None, []
    parts = [
        f"P{d.proposal_id} {ACTION_LABEL.get(d.action, d.action)} (사유: '{d.rationale}')"
        for d in decisions
    ]
    return "; ".join(parts), [d.evidence.key for d in decisions if d.evidence]


def _status(alt: AlternativeExplanation) -> AlternativeExplanation:
    sup = sum(1 for a in alt.supporting if a.basis == "data")
    opp = sum(1 for a in alt.opposing if a.basis == "data")
    if opp > sup:
        alt.status = "weakened"
    elif sup:
        alt.status = "plausible"
    else:
        alt.status = "untested"
    return alt


def assess_recovery_cause(ctx: CritiqueContext) -> CriticAssessment | None:
    """Structured critique of a low/dropped recovery; ``None`` when nothing to explain."""
    ev, c, exp = ctx.evidence, ctx.criteria, ctx.experiment
    mean = ev.get("recovery_mean")
    if mean is None:
        return None
    failing = ctx.failing_analytes()
    delta, p = ev.get("recovery_delta"), ev.get("recovery_p")
    base_mean = ev.get("baseline_recovery_mean")
    dropped = bool(
        delta and delta.value is not None and delta.value < 0 and p and (p.value or 1.0) < 0.05
    )
    if not failing and not dropped:
        return None

    changes = ctx.pretreatment_changes
    change_evs = [e for ch in changes if (e := ev.get(f"change:{ch.key}"))]
    labels = ", ".join(ch.label for ch in changes)
    failing_evs = [e for a in failing if (e := ev.get(f"recovery:{a}"))]
    is_flagged, is_total = ev.get("is_flagged"), ev.get("is_total")
    is_dev = bool(is_flagged and is_flagged.value)
    is_injections = ev.prefixed("is_injection:")
    cal_ev, stage_ev = ev.get("calibration_type"), ev.get("is_addition_stage")
    me_evs = ev.prefixed("me:")
    me_sig = ev.prefixed("me_significant:")
    me_proto = ev.prefixed("me_protocol:")
    fail_levels = ev.prefixed("fail_levels:")
    gcb = gcb_introduced(ctx)
    pattern = planar_pattern(ctx)

    claim = (
        f"{exp.code}의 회수율 저하는 전처리({labels}) 변경에 따른 손실 때문이다"
        if changes
        else f"{exp.code}의 회수율 저하는 전처리 손실(실제 추출 효율 저하) 때문이다"
    )

    # ------------------------------------------------------------- 지지 근거
    supporting: list[CriticArgument] = []
    if changes and ctx.baseline and base_mean and dropped and delta and p and p.value is not None:
        supporting.append(
            CriticArgument(
                statement=(
                    f"{ctx.baseline.code} 대비 전처리 조건({labels})이 바뀐 실험에서 평균 회수율이 "
                    f"{fmt(base_mean)} → {fmt(mean)}로 낮아졌다 (변화 {fmt(delta)}, "
                    f"Welch t-test {fmt_p(p.value)})."
                ),
                evidence_keys=_keys(*change_evs, base_mean, mean, delta, p),
            )
        )
    if failing_evs:
        supporting.append(
            CriticArgument(
                statement=(
                    "허용 범위("
                    f"{c.recovery_min_pct:g}–{c.recovery_max_pct:g}%)를 벗어난 분석물: "
                    + ", ".join(f"{e.label.split(' ')[1]} {fmt(e)}" for e in failing_evs)
                    + "."
                ),
                evidence_keys=_keys(*failing_evs),
            )
        )
    adsorption_args: list[CriticArgument] = []
    ionisation_args: list[CriticArgument] = []
    nonplanar_args: list[CriticArgument] = []
    if gcb and pattern:
        planar, _others = pattern
        supporting.append(
            CriticArgument(
                statement=(
                    "평면 구조 분석물의 감소 폭("
                    + ", ".join(f"{d.label.split(' ')[0]} {fmt(d)}" for d in planar)
                    + f")이 다른 모든 분석물보다 커서 {gcb} 흡착 손실 패턴과 일치한다."
                ),
                evidence_keys=_keys(*planar),
            )
        )
        supporting.append(
            CriticArgument(
                statement=f"{SORBENT_NOTES[gcb]}.",
                evidence_keys=_keys(ev.get("change:cleanup_sorbent")),
                basis="domain_rule",
            )
        )
        adsorption_args = supporting[-2:]

    # ------------------------------------------------------------- 반대 근거
    opposing: list[CriticArgument] = []
    if is_dev and is_flagged and is_total:
        opposing.append(
            CriticArgument(
                statement=(
                    f"IS 응답이 {is_flagged.value:.0f}/{is_total.value:.0f}회 주입에서 기준"
                    f"({c.is_response_min_pct:g}–{c.is_response_max_pct:g}%)을 벗어났다. 분석물 "
                    "손실만으로는 설명되지 않는 이온화 억제(매트릭스 효과) 징후다."
                ),
                evidence_keys=_keys(is_flagged, is_total, *is_injections),
            )
        )
        ionisation_args.append(opposing[-1])
    if pattern:
        _planar, others = pattern
        if all((o.value or 0.0) < 0 for o in others):
            opposing.append(
                CriticArgument(
                    statement=(
                        "평면 구조가 아닌 분석물도 함께 감소했다("
                        + ", ".join(f"{d.label.split(' ')[0]} {fmt(d)}" for d in others)
                        + "). 흡착 손실만으로는 설명되지 않으며 추출 불완전 또는 전반적 이온화 "
                        "억제와도 양립한다."
                    ),
                    evidence_keys=_keys(*others),
                )
            )
            nonplanar_args.append(opposing[-1])
    if me_sig:
        worst = min(me_sig, key=lambda e: e.value or 0.0)
        opposing.append(
            CriticArgument(
                statement=(
                    f"프로젝트 기록상 이 매트릭스는 기준(±{c.matrix_effect_abs_max_pct:g}%)을 넘는 "
                    f"신호 억제를 일으킨 적이 있다: {worst.label} {fmt(worst)}."
                ),
                evidence_keys=_keys(*me_sig),
            )
        )
        ionisation_args.append(opposing[-1])

    # ------------------------------------------------------------- 누락 대조군
    missing: list[MissingControl] = []

    def add_control(control_id: str, keys: list[str]) -> None:
        spec = CONTROLS[control_id]
        note, dkeys = decision_note(ctx.decisions.for_control(control_id))
        missing.append(
            MissingControl(
                id=spec.id,
                name=spec.name,
                purpose=spec.purpose,
                distinguishes=list(spec.distinguishes),
                evidence_keys=keys + dkeys,
                decision_note=note,
            )
        )

    separated = ctx.post_spike_recorded or ctx.me_transferable
    if not separated:
        add_control("pre_post_spike", _keys(cal_ev, *me_proto))
    if not ctx.matrix_matched:
        add_control("matrix_matched_calibration", _keys(cal_ev, *me_sig))
    if len(changes) > 1:
        add_control("single_variable", _keys(*change_evs))
    if is_dev and not ctx.is_stage_recorded:
        add_control("is_addition_record", _keys(stage_ev, is_flagged))

    # ------------------------------------------------------------- 대안 설명
    alternatives: list[AlternativeExplanation] = []
    changed_expl = {EXPLANATION_FOR_KEY.get(ch.key) for ch in changes}
    if "extraction_incomplete" in changed_expl or not changes:
        spec = EXPLANATIONS["extraction_incomplete"]
        sup = [
            CriticArgument(statement=f"{e.text}.", evidence_keys=[e.key])
            for ch in changes
            if EXPLANATION_FOR_KEY.get(ch.key) == "extraction_incomplete"
            and (e := ev.get(f"change:{ch.key}"))
        ]
        opp: list[CriticArgument] = []
        if pattern:
            opp.append(
                CriticArgument(
                    statement="추출 조건 변화만으로는 평면 구조 분석물의 선택적 큰 감소를 설명하기 "
                    "어렵다.",
                    evidence_keys=_keys(*pattern[0]),
                )
            )
        alternatives.append(
            _status(
                AlternativeExplanation(
                    id=spec.id,
                    label=spec.label,
                    mechanism=spec.mechanism,
                    supporting=sup,
                    opposing=opp,
                )
            )
        )
    if "cleanup_adsorption" in changed_expl:
        spec = EXPLANATIONS["cleanup_adsorption"]
        sup = list(adsorption_args)
        opp = list(nonplanar_args)
        alternatives.append(
            _status(
                AlternativeExplanation(
                    id=spec.id,
                    label=spec.label,
                    mechanism=spec.mechanism,
                    supporting=sup,
                    opposing=opp,
                )
            )
        )
    me_spec = EXPLANATIONS["matrix_suppression"]
    me_sup = list(ionisation_args)
    if not ctx.matrix_matched and cal_ev:
        me_sup.append(
            CriticArgument(
                statement="용매 표준 검량선으로 정량해 이온화 억제가 보정되지 않은 채 회수율에 "
                "반영된다.",
                evidence_keys=[cal_ev.key],
            )
        )
    me_opp: list[CriticArgument] = []
    planar_me = [e for e in me_evs if e.label.split(" ")[1] in PLANAR_ANALYTES]
    if planar_me and all(abs(e.value or 0.0) <= c.matrix_effect_abs_max_pct for e in planar_me):
        me_exp_code = ctx.project_matrix_effect[0].code if ctx.project_matrix_effect else ""
        caveat = " 단, 그 측정은 다른 전처리 조건에서 이루어졌다." if me_proto else ""
        me_opp.append(
            CriticArgument(
                statement=(
                    f"{me_exp_code} 측정에서 평면 구조 분석물의 매트릭스 효과는 기준 이내였다("
                    + ", ".join(f"{e.label.split(' ')[1]} {fmt(e)}" for e in planar_me)
                    + ")."
                    + caveat
                ),
                evidence_keys=_keys(*planar_me, *me_proto),
            )
        )
    alternatives.append(
        _status(
            AlternativeExplanation(
                id=me_spec.id,
                label=me_spec.label,
                mechanism=me_spec.mechanism,
                supporting=me_sup,
                opposing=me_opp,
            )
        )
    )
    if is_dev and is_flagged and is_total:
        spec = EXPLANATIONS["is_correction_bias"]
        bias_opp: list[CriticArgument] = []
        if (
            fail_levels
            and is_flagged.value is not None
            and is_total.value is not None
            and is_flagged.value < is_total.value
        ):
            bias_opp.append(
                CriticArgument(
                    statement=(
                        "기준 미달이 모든 첨가 수준에서 나타나("
                        + "; ".join(f"{e.label.split(' ')[1]}: {e.text}" for e in fail_levels)
                        + ") 일부 주입의 IS 이탈만으로는 설명되지 않는다."
                    ),
                    evidence_keys=_keys(*fail_levels, is_flagged),
                )
            )
        alternatives.append(
            _status(
                AlternativeExplanation(
                    id=spec.id,
                    label=spec.label,
                    mechanism=spec.mechanism,
                    supporting=[
                        CriticArgument(
                            statement=(
                                f"IS 응답 이탈 주입이 {is_flagged.value:.0f}/"
                                f"{is_total.value:.0f}회 있다 (시료 특이적 억제 패턴)."
                            ),
                            evidence_keys=_keys(is_flagged, is_total, *is_injections),
                        )
                    ],
                    opposing=bias_opp,
                )
            )
        )

    # ------------------------------------------------ 현재 데이터로 확정 불가한 이유
    undetermined: list[CriticArgument] = []
    if not ctx.matrix_matched and cal_ev:
        undetermined.append(
            CriticArgument(
                statement=(
                    "회수율이 용매 표준 검량선 기준으로 계산되어, 측정된 값은 추출·정제 손실과 "
                    "이온화 억제가 곱해진 '겉보기 회수율'이다. 이 값만으로는 두 요인을 나눌 수 "
                    "없다."
                ),
                evidence_keys=_keys(cal_ev, mean),
                basis="domain_rule",
            )
        )
    if ctx.project_matrix_effect is None:
        undetermined.append(
            CriticArgument(
                statement="프로젝트에 매트릭스 효과 측정 기록이 없다.",
                evidence_keys=_keys(cal_ev),
            )
        )
    elif me_proto:
        me_exp = ctx.project_matrix_effect[0]
        undetermined.append(
            CriticArgument(
                statement=(
                    f"매트릭스 효과는 {me_exp.code}의 전처리 조건에서만 측정되었고 이후 "
                    + ", ".join(e.text or e.label for e in me_proto)
                    + f"(으)로 바뀌어 {exp.code} 추출액의 매트릭스 효과는 측정된 적이 없다."
                ),
                evidence_keys=_keys(*me_proto, *me_evs),
            )
        )
    if not separated:
        undetermined.append(
            CriticArgument(
                statement=(
                    f"{exp.code} 프로토콜로 수행한 추출 전·후 첨가 비교 데이터가 없어 추출 "
                    "회수율과 매트릭스 효과를 분리할 수 없다."
                ),
                evidence_keys=_keys(cal_ev),
            )
        )
    if len(changes) > 1:
        undetermined.append(
            CriticArgument(
                statement=(
                    f"전처리 조건({labels})이 동시에 바뀌어 전처리 손실이 맞더라도 어느 조건 "
                    "때문인지 귀속할 수 없다."
                ),
                evidence_keys=_keys(*change_evs),
            )
        )
    if is_dev and not ctx.is_stage_recorded and stage_ev:
        undetermined.append(
            CriticArgument(
                statement=(
                    "IS 첨가 시점(추출 전/후)이 기록되지 않아 IS 보정이 전처리 손실까지 "
                    "상쇄했는지 판단할 수 없다. IS 이탈 주입과 정상 주입의 회수율을 나눈 "
                    "Analysis 결과도 아직 없다."
                ),
                evidence_keys=_keys(stage_ev, is_flagged),
            )
        )
    for d in ctx.decisions.decisions:
        if d.rejected and d.reason_category in ("scientific", "already_done", "priority"):
            if set(d.addresses_controls) & {m.id for m in missing}:
                undetermined.append(
                    CriticArgument(
                        statement=(
                            f"P{d.proposal_id}('{d.title}')이 '{d.rationale}' 사유로 기각되어 "
                            "해당 대조군 데이터가 여전히 기록되어 있지 않다."
                        ),
                        evidence_keys=_keys(d.evidence),
                        basis="decision",
                    )
                )

    # ------------------------------------------------------------------ 판정
    if not separated and not ctx.matrix_matched:
        verdict = "indeterminate"
        reason = (
            "전처리 손실과 매트릭스 효과를 현재 데이터로 구분 불가 — "
            + ", ".join(
                m.name for m in missing if m.id in ("pre_post_spike", "matrix_matched_calibration")
            )
            + " 데이터가 없다."
        )
    elif len(changes) > 1:
        verdict = "indeterminate"
        reason = (
            "매트릭스 효과는 분리되었으나 동시에 바뀐 전처리 조건 중 어느 것이 손실 원인인지 "
            "구분 불가."
        )
    else:
        verdict = "supported"
        reason = (
            "같은 전처리 조건에서 매트릭스 효과가 분리되어 있어, 남은 회수율 저하는 전처리 "
            "손실로 해석할 수 있다."
        )

    return CriticAssessment(
        id="recovery_cause",
        question=f"{exp.code} 회수율 저하의 원인: 전처리 손실인가, 매트릭스 효과인가?",
        claim=claim,
        verdict=verdict,
        verdict_reason=reason,
        supporting_evidence=supporting,
        opposing_evidence=opposing,
        missing_controls=missing,
        alternative_explanations=alternatives,
        undetermined_reasons=undetermined,
    )


def describe_change(ctx: CritiqueContext, key: str) -> str:
    """``label a → b`` for a changed condition key (empty if unchanged)."""
    for ch in ctx.pretreatment_changes:
        if ch.key == key:
            return f"{ch.label} {format_value(ch.value_a)} → {format_value(ch.value_b)}"
    return ""
