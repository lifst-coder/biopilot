"""Next Experiment Designer (rules mode).

For every missing control in the Critic's assessment the designer instantiates the
first design template (``knowledge.DESIGNS_FOR_CONTROL``) that is *not excluded by the
Decision History*:

* a decided proposal is never re-proposed (same :func:`proposal_signature`);
* a rejection whose rationale names an unavailable resource (e.g. "블랭크 확보 불가")
  excludes every template requiring it, so the next alternative is chosen and records
  ``supersedes_proposal_ids``;
* a rejection judged scientific/already-done drops the control; "priority" defers it;
* an accepted/modified proposal on the control means it is being addressed — no
  alternative is offered.

Each design states variables, controls, replicates (copied from stored recovery
groups), measurements, expected outcomes and discriminating power, and cites the
experiments it is based on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.eln.schemas import CONDITION_FIELD_LABELS
from app.partner.context import CritiqueContext, format_value
from app.partner.feedback import ACTION_LABEL, PriorDecision, proposal_signature
from app.partner.knowledge import (
    DESIGNS,
    DESIGNS_FOR_CONTROL,
    EXPLANATION_FOR_KEY,
    PRETREATMENT_KEYS,
    RECOVERY_MECHANISMS,
    DesignTemplate,
)
from app.partner.schemas import (
    CriticAssessment,
    DecisionFeedback,
    DesignControl,
    DesignVariable,
    ExpectedOutcome,
    ExperimentDesign,
    ProposalChange,
    ProposalDraft,
)

Instantiator = Callable[[CritiqueContext, dict[str, int]], list[ProposalDraft]]


def _base_design(ctx: CritiqueContext, t: DesignTemplate, basis: list[int]) -> ExperimentDesign:
    reps = ctx.evidence.get("replicates")
    return ExperimentDesign(
        template_id=t.id,
        objective=t.objective,
        replicates=int(reps.value) if reps and reps.value is not None else None,
        replicates_basis=f"{reps.label} 기준" if reps else None,
        replicates_evidence_key=reps.key if reps else None,
        measurements=list(t.measurements),
        discriminating_power=t.power,
        discriminates=list(t.discriminates),
        power_rationale=t.power_rationale,
        addresses_controls=list(t.addresses),
        basis_experiment_ids=sorted(set(basis)),
        requires=list(t.requires),
    )


def _fixed_pretreatment(ctx: CritiqueContext, exclude: set[str]) -> list[DesignVariable]:
    labels = {c.key: c.label for c in (ctx.diff.condition_changes if ctx.diff else [])}
    labels = {**CONDITION_FIELD_LABELS, **labels}
    out: list[DesignVariable] = []
    for key in PRETREATMENT_KEYS:
        if key in exclude or key not in ctx.conditions:
            continue
        value = ctx.conditions[key]
        out.append(
            DesignVariable(
                key=key,
                label=labels.get(key, key),
                role="fixed",
                levels=[value if isinstance(value, str | float | int) else format_value(value)],
            )
        )
    return out


def _failing_keys(ctx: CritiqueContext) -> list[str]:
    return [e.key for a in ctx.failing_analytes() if (e := ctx.evidence.get(f"recovery:{a}"))]


def _basis(ctx: CritiqueContext) -> list[int]:
    ids = [ctx.experiment.id]
    if ctx.baseline:
        ids.append(ctx.baseline.id)
    if ctx.project_matrix_effect:
        ids.append(ctx.project_matrix_effect[0].id)
    return ids


def _pre_post_spike(ctx: CritiqueContext, hyp: dict[str, int]) -> list[ProposalDraft]:
    t = DESIGNS["pre_post_spike"]
    c = ctx.criteria
    design = _base_design(ctx, t, _basis(ctx))
    design.variables = [
        DesignVariable(
            key="spike_stage",
            label="첨가 시점",
            role="varied",
            levels=["추출 전 첨가 (pre)", "추출 후 첨가 (post)", "용매 표준"],
        ),
        *_fixed_pretreatment(ctx, set()),
    ]
    design.controls = [
        DesignControl(name="블랭크 추출액 (무첨가)", purpose="간섭 피크·바탕값 확인"),
        DesignControl(name="용매 표준 (같은 첨가 수준)", purpose="매트릭스 효과 계산의 기준"),
    ]
    design.expected_outcomes = [
        ExpectedOutcome(
            observation="post ≈ 용매 표준, pre < post",
            interpretation="낮은 회수율은 전처리(추출·정제) 손실이다",
            supports=["extraction_incomplete", "cleanup_adsorption"],
        ),
        ExpectedOutcome(
            observation=f"post가 용매 표준보다 기준(±{c.matrix_effect_abs_max_pct:g}%) 넘게 낮고 "
            "pre ≈ post",
            interpretation="낮은 회수율은 매트릭스 효과(이온화 억제)다",
            supports=["matrix_suppression"],
        ),
        ExpectedOutcome(
            observation="pre < post 이면서 post도 용매 표준보다 낮음",
            interpretation="전처리 손실과 매트릭스 효과가 혼재 — 각각의 크기를 분리 정량",
            supports=["extraction_incomplete", "cleanup_adsorption", "matrix_suppression"],
        ),
    ]
    return [
        ProposalDraft(
            title=t.title,
            description=(
                f"{ctx.experiment.code} 프로토콜 그대로 블랭크 시료를 추출해 추출 전·후 첨가 "
                "시료와 용매 표준을 같은 수준으로 비교한다. RE·ME·PE 계산은 Analysis 계층에서 "
                "수행한다."
            ),
            changes=[
                ProposalChange(key="spike_stage", value="pre-extraction + post-extraction"),
                # ``calibration_type`` names the curve Analysis quantifies with and must stay
                # in the contract domain (solvent | matrix-matched | standard-addition).
                # The post-extraction spike *is* the matrix-matched curve; the solvent
                # curve is the comparison for the matrix effect, recorded separately.
                ProposalChange(key="calibration_type", value="matrix-matched"),
                ProposalChange(key="curves_compared", value="solvent + matrix-matched"),
            ],
            evidence_keys=[
                k
                for k in (
                    *(e.key for e in ctx.evidence.prefixed("calibration_type")),
                    *(e.key for e in ctx.evidence.prefixed("me_protocol:")),
                    *_failing_keys(ctx),
                )
            ],
            hypothesis_index=hyp.get("__matrix__", hyp.get("cleanup_sorbent")),
            design=design,
            base_experiment_id=ctx.experiment.id,
        )
    ]


def _standard_addition(ctx: CritiqueContext, hyp: dict[str, int]) -> list[ProposalDraft]:
    t = DESIGNS["standard_addition"]
    design = _base_design(ctx, t, _basis(ctx))
    design.variables = [
        DesignVariable(
            key="post_addition_level",
            label="추출액 후첨가 수준",
            role="varied",
            levels=["무첨가", "검량 범위 내 수준 (연구자 정의)"],
        ),
        *_fixed_pretreatment(ctx, set()),
    ]
    design.controls = [
        DesignControl(name="용매 검량선 (같은 배치)", purpose="기울기 비 계산의 기준"),
        DesignControl(name="무첨가 추출액", purpose="시료 고유 신호 확인"),
    ]
    design.expected_outcomes = [
        ExpectedOutcome(
            observation="시료 추출액 기울기 ≈ 용매 기울기",
            interpretation="매트릭스 효과가 작다 — 낮은 회수율은 전처리 손실로 해석",
            supports=["extraction_incomplete", "cleanup_adsorption"],
        ),
        ExpectedOutcome(
            observation="시료 추출액 기울기 < 용매 기울기",
            interpretation="이온화 억제가 겉보기 회수율 저하에 기여한다",
            supports=["matrix_suppression"],
        ),
    ]
    return [
        ProposalDraft(
            title=t.title,
            description=(
                f"{ctx.experiment.code}에서 이미 확보한 시료 추출액에 표준물을 후첨가해 시료별 "
                "기울기를 구한다. 블랭크 매트릭스가 없어도 수행할 수 있다."
            ),
            changes=[ProposalChange(key="calibration_type", value="standard-addition")],
            evidence_keys=[
                *(e.key for e in ctx.evidence.prefixed("calibration_type")),
                *_failing_keys(ctx),
            ],
            hypothesis_index=hyp.get("__matrix__"),
            design=design,
            base_experiment_id=ctx.experiment.id,
        )
    ]


def _factorial(ctx: CritiqueContext, hyp: dict[str, int]) -> list[ProposalDraft]:
    changes = ctx.pretreatment_changes
    if ctx.baseline is None or len(changes) != 2:
        return []
    t = DESIGNS["factorial_pretreatment"]
    design = _base_design(ctx, t, _basis(ctx))
    design.variables = [
        DesignVariable(key=ch.key, label=ch.label, role="varied", levels=[ch.value_a, ch.value_b])
        for ch in changes
    ] + _fixed_pretreatment(ctx, {ch.key for ch in changes})
    design.controls = [
        DesignControl(
            name=f"기준 조합 셀 ({ctx.baseline.code} 조건)",
            purpose="같은 배치 안에서 기준 회수율 재현 확인 (배치 효과 통제)",
        ),
        DesignControl(name="블랭크 추출액", purpose="간섭 확인"),
    ]
    a, b = changes
    design.expected_outcomes = [
        ExpectedOutcome(
            observation=f"{a.label}의 주효과만 유의",
            interpretation=f"회수율 저하는 {a.label} 변경 때문이다",
            supports=[_expl(a.key)],
        ),
        ExpectedOutcome(
            observation=f"{b.label}의 주효과만 유의",
            interpretation=f"회수율 저하는 {b.label} 변경 때문이다",
            supports=[_expl(b.key)],
        ),
        ExpectedOutcome(
            observation="교호작용 유의",
            interpretation="두 조건이 함께 작용한다 — 단일 변수 실험으로는 놓쳤을 효과",
            supports=[_expl(a.key), _expl(b.key)],
        ),
    ]
    change_keys = [e.key for ch in changes if (e := ctx.evidence.get(f"change:{ch.key}"))]
    return [
        ProposalDraft(
            title=t.title,
            description=(
                f"{ctx.baseline.code} 기준 프로토콜에서 {a.label}({format_value(a.value_a)} / "
                f"{format_value(a.value_b)})과 {b.label}을 교차 배치한 네 셀을 같은 배치로 "
                "수행한다. 주효과·교호작용 검정은 Analysis 계층에서 수행한다."
            ),
            changes=[
                ProposalChange(key="design", value="factorial 2x2"),
                *(
                    ProposalChange(
                        key=f"factor_{ch.key}",
                        value=f"{format_value(ch.value_a)} | {format_value(ch.value_b)}",
                    )
                    for ch in changes
                ),
            ],
            evidence_keys=change_keys + _failing_keys(ctx),
            hypothesis_index=hyp.get("cleanup_sorbent", hyp.get(a.key)),
            design=design,
            base_experiment_id=ctx.baseline.id,
        )
    ]


def _expl(key: str) -> str:
    return EXPLANATION_FOR_KEY.get(key, "extraction_incomplete")


def _single_variable(ctx: CritiqueContext, hyp: dict[str, int]) -> list[ProposalDraft]:
    if ctx.baseline is None:
        return []
    t = DESIGNS["single_variable"]
    out: list[ProposalDraft] = []
    for ch in ctx.pretreatment_changes:
        if ch.key not in RECOVERY_MECHANISMS:
            continue
        change_ev = ctx.evidence.get(f"change:{ch.key}")
        design = _base_design(ctx, t, _basis(ctx))
        design.addresses_controls = ["single_variable"]
        design.variables = [
            DesignVariable(
                key=ch.key, label=ch.label, role="varied", levels=[ch.value_a, ch.value_b]
            ),
            *_fixed_pretreatment(ctx, {ch.key}),
        ]
        design.controls = [
            DesignControl(
                name=f"{ctx.baseline.code} 기준 프로토콜 병행",
                purpose="같은 배치에서 기준값 재현 (배치 효과 통제)",
            )
        ]
        design.discriminates = [_expl(ch.key)]
        design.expected_outcomes = [
            ExpectedOutcome(
                observation=f"{ch.label}만 바꿔도 회수율이 기준 미달로 떨어짐",
                interpretation=f"{ch.label} 변경이 손실 원인이다",
                supports=[_expl(ch.key)],
            ),
            ExpectedOutcome(
                observation="회수율이 기준 프로토콜과 같음",
                interpretation=f"{ch.label}은 단독 원인이 아니다",
                supports=[],
            ),
        ]
        out.append(
            ProposalDraft(
                title=f"단일 변수 실험: {ch.label}만 변경",
                description=(
                    f"{ctx.baseline.code} 기준 프로토콜에서 {ch.label}만 "
                    f"{format_value(ch.value_b)}(으)로 바꾸고 나머지는 유지해 영향을 분리한다."
                ),
                changes=[ProposalChange(key=ch.key, value=ch.value_b)],
                evidence_keys=[change_ev.key] if change_ev else [],
                hypothesis_index=hyp.get(ch.key),
                design=design,
                base_experiment_id=ctx.baseline.id,
            )
        )
    return out


def _dilution(template_id: str) -> Instantiator:
    def build(ctx: CritiqueContext, hyp: dict[str, int]) -> list[ProposalDraft]:
        is_flagged = ctx.evidence.get("is_flagged")
        if not is_flagged or not is_flagged.value:
            return []
        t = DESIGNS[template_id]
        design = _base_design(ctx, t, _basis(ctx))
        design.variables = [
            DesignVariable(
                key="injection_dilution",
                label="희석 배율",
                role="varied",
                levels=["무희석", "희석 (연구자 정의)"],
            )
        ]
        design.controls = [
            DesignControl(name="IS 정상 주입 시료 동일 희석", purpose="희석 자체의 영향 통제")
        ]
        design.expected_outcomes = [
            ExpectedOutcome(
                observation="희석 후 IS 응답이 기준 범위로 회복",
                interpretation="해당 시료의 IS 이탈은 이온화 억제(매트릭스 효과)다",
                supports=["matrix_suppression", "is_correction_bias"],
            ),
            ExpectedOutcome(
                observation="희석해도 IS 응답이 낮음",
                interpretation="IS 첨가·회수 과정의 문제 — IS 첨가 시점 기록 필요",
                supports=["is_correction_bias"],
            ),
        ]
        injection_keys = [e.key for e in ctx.evidence.prefixed("is_injection:")]
        if template_id == "dilution_reinjection":
            changes = [
                ProposalChange(key="injection_dilution", value="researcher-defined"),
                ProposalChange(key="calibration_type", value="matrix-matched"),
            ]
        else:
            changes = [
                ProposalChange(key="injection_dilution", value="series (researcher-defined)")
            ]
        return [
            ProposalDraft(
                title=t.title,
                description=t.objective,
                changes=changes,
                evidence_keys=[is_flagged.key, *injection_keys],
                hypothesis_index=hyp.get("__matrix__"),
                design=design,
                base_experiment_id=ctx.experiment.id,
            )
        ]

    return build


INSTANTIATE: dict[str, Instantiator] = {
    "pre_post_spike": _pre_post_spike,
    "standard_addition": _standard_addition,
    "factorial_pretreatment": _factorial,
    "single_variable": _single_variable,
    "dilution_reinjection": _dilution("dilution_reinjection"),
    "dilution_series": _dilution("dilution_series"),
}


@dataclass
class DesignResult:
    proposals: list[ProposalDraft] = field(default_factory=list)
    feedback: list[DecisionFeedback] = field(default_factory=list)


@dataclass
class _Selection:
    proposals: list[ProposalDraft] = field(default_factory=list)
    blocked: dict[int, PriorDecision] = field(default_factory=dict)


def _select_for_control(
    ctx: CritiqueContext, control_id: str, hyp: dict[str, int], sel: _Selection
) -> None:
    """Append the first non-excluded design for one control to ``sel``."""
    memory = ctx.decisions
    by_signature: dict[str, list[PriorDecision]] = {}
    for d in memory.decisions:
        by_signature.setdefault(d.signature, []).append(d)
        if d.modifications:
            by_signature.setdefault(proposal_signature(d.modifications), []).append(d)
    deferred = memory.deferred_templates()
    superseded: list[int] = []
    for tid in DESIGNS_FOR_CONTROL[control_id]:
        template = DESIGNS[tid]
        drafts = INSTANTIATE[tid](ctx, hyp)
        if not drafts:
            continue
        matches = {id(p): by_signature.get(proposal_signature(p.changes), []) for p in drafts}
        repeated = [d for found in matches.values() for d in found]
        if any(not d.rejected for d in repeated):
            # Accepted/modified: this control is being addressed — offer nothing new.
            sel.blocked.update({d.decision_id: d for d in repeated})
            return
        blockers = [
            d
            for d in memory.decisions
            if d.rejected
            and (
                set(d.constraints) & set(template.requires)
                or (tid in deferred and d.template_id == tid)
            )
        ]
        if blockers:
            sel.blocked.update({d.decision_id: d for d in blockers})
            superseded += [
                d.proposal_id
                for d in blockers
                if control_id in d.addresses_controls or d.template_id == tid
            ]
            continue
        sel.blocked.update({d.decision_id: d for d in repeated})
        remaining = [p for p in drafts if not matches[id(p)]]
        if not remaining:
            superseded += [d.proposal_id for d in repeated]
            continue
        for p in remaining:
            p.supersedes_proposal_ids = sorted(set(superseded))
        sel.proposals.extend(remaining)
        return


def design_next_experiments(
    ctx: CritiqueContext, assessment: CriticAssessment | None, hyp: dict[str, int]
) -> DesignResult:
    """Proposals for the assessment's missing controls, filtered by the Decision History."""
    result = DesignResult()
    if assessment is None:
        return result
    sel = _Selection()
    dismissed = ctx.decisions.dismissed_controls()
    covered: set[str] = set()
    for control in assessment.missing_controls:
        if control.id in dismissed or control.id in covered:
            continue
        before = len(sel.proposals)
        _select_for_control(ctx, control.id, hyp, sel)
        for p in sel.proposals[before:]:
            covered |= set(p.design.addresses_controls if p.design else [])
    unique: dict[str, ProposalDraft] = {}
    for p in sel.proposals:
        unique.setdefault(proposal_signature(p.changes), p)
    result.proposals = list(unique.values())
    result.feedback = _feedback(ctx, result.proposals, sel)
    return result


def _feedback(
    ctx: CritiqueContext, proposals: list[ProposalDraft], sel: _Selection
) -> list[DecisionFeedback]:
    out: list[DecisionFeedback] = []
    for d in ctx.decisions.decisions:
        relevant = (
            d.experiment_id == ctx.experiment.id or d.decision_id in sel.blocked or d.constraints
        )
        if not relevant:
            continue
        label = ACTION_LABEL.get(d.action, d.action)
        alt = next((p for p in proposals if d.proposal_id in p.supersedes_proposal_ids), None)
        if not d.rejected:
            applied, note = (
                "awaiting_result",
                f"P{d.proposal_id} {label}됨 — 후속 실험 결과가 기록되면 판정에 반영한다. "
                "같은 제안은 다시 만들지 않는다.",
            )
        elif alt is not None:
            applied, note = (
                "alternative_proposed",
                f"P{d.proposal_id} 기각 사유('{d.rationale}')를 반영해 같은 제안을 반복하지 "
                f"않고 '{alt.title}'(으)로 대체했다.",
            )
        elif d.reason_category in ("scientific", "already_done"):
            applied, note = (
                "noted",
                f"P{d.proposal_id} 기각 사유('{d.rationale}')에 따라 같은 대조군 설계를 다시 "
                "제안하지 않는다.",
            )
        elif d.reason_category == "priority":
            applied, note = (
                "suppressed_repeat",
                f"P{d.proposal_id} 보류('{d.rationale}') — 이번 제안에서 제외했다.",
            )
        else:
            applied, note = (
                "suppressed_repeat",
                f"P{d.proposal_id} 기각('{d.rationale}') — 같은 제안을 반복하지 않는다.",
            )
        out.append(
            DecisionFeedback(
                decision_id=d.decision_id,
                proposal_id=d.proposal_id,
                action=d.action,
                rationale=d.rationale,
                reason_category=d.reason_category,
                applied=applied,
                note=note,
                evidence_key=d.evidence.key if d.evidence else None,
            )
        )
    return out


__all__ = ["DesignResult", "design_next_experiments"]
