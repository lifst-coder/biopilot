"""Project-level rules critique (PAR-7): trends across all experiments.

Example output: "회수율 기준 미달이 정제 흡착제 = …GCB… 조건 실험에만 나타남". The engine
compares condition values of failing vs. passing experiments (set membership only —
no arithmetic) and emits the same :class:`CritiqueDraft` schema as experiment critiques.
"""

from __future__ import annotations

from app.eln.schemas import CONDITION_FIELD_LABELS, ExperimentOut
from app.partner.context import ProjectContext, condition_evidence, format_value
from app.partner.engines.critic import decision_note
from app.partner.knowledge import CONTROLS
from app.partner.schemas import (
    CriticArgument,
    CriticAssessment,
    CritiqueDraft,
    Finding,
    HypothesisDraft,
    MissingControl,
)

#: Keys that describe the sample/instrument rather than a method variable.
IGNORED_KEYS: frozenset[str] = frozenset({"matrix", "instrument"})


def _label(key: str) -> str:
    return CONDITION_FIELD_LABELS.get(key, key)


def _localised_keys(
    failing: list[ExperimentOut], passing: list[ExperimentOut]
) -> list[tuple[str, object]]:
    """Condition (key, value) shared by every failing and no passing experiment."""
    out: list[tuple[str, object]] = []
    first = failing[0].condition_block.model_dump(exclude_none=True)
    for key, value in first.items():
        if key in IGNORED_KEYS:
            continue
        if any(e.condition_block.model_dump().get(key) != value for e in failing[1:]):
            continue
        if any(e.condition_block.model_dump().get(key) == value for e in passing):
            continue
        out.append((key, value))
    return out


class ProjectRulesEngine:
    """Deterministic project-scope critique."""

    name = "rules"

    def critique(self, ctx: ProjectContext) -> CritiqueDraft:
        ev = ctx.evidence
        findings: list[Finding] = []
        hypotheses: list[HypothesisDraft] = []
        assessments: list[CriticAssessment] = []
        with_recovery = [e for e in ctx.experiments if ev.get(f"recovery_mean:{e.code}")]
        failing = [e for e in with_recovery if ev.get(f"failing:{e.code}")]
        passing = [e for e in with_recovery if not ev.get(f"failing:{e.code}")]

        if failing and passing:
            localised = _localised_keys(failing, passing)
            f_codes = ", ".join(e.code for e in failing)
            p_codes = ", ".join(e.code for e in passing)
            cond_keys = [
                condition_evidence(ctx, e, k, _label(k)).key for k, _v in localised for e in failing
            ]
            rec_keys = [
                k.key
                for e in with_recovery
                for k in (ev.get(f"recovery_mean:{e.code}"), ev.get(f"failing:{e.code}"))
                if k
            ]
            if localised:
                desc = ", ".join(f"{_label(k)} = {format_value(v)}" for k, v in localised)
                body = (
                    f"기준 미달 실험({f_codes})에만 {desc} 조건이 있고, 기준 충족 실험({p_codes})"
                    "에는 이 값이 없다."
                )
                if len(localised) > 1:
                    body += (
                        " 이 조건들이 같은 실험에서 함께 바뀌어 어느 조건 때문인지 분리할 수 없다."
                    )
                findings.append(
                    Finding(
                        title="회수율 기준 미달이 "
                        + ", ".join(_label(k) for k, _v in localised)
                        + " 변경 실험에만 나타남",
                        body=body,
                        severity="warning",
                        evidence_keys=rec_keys + cond_keys,
                    )
                )
                for k, v in localised:
                    hypotheses.append(
                        HypothesisDraft(
                            statement=f"{_label(k)} = {format_value(v)} 조건이 회수율 기준 미달의 "
                            "원인이다",
                            rationale=f"이 조건은 기준 미달 실험({f_codes})에만 나타난다.",
                            evidence_keys=[
                                condition_evidence(ctx, e, k, _label(k)).key for e in failing
                            ]
                            + rec_keys,
                        )
                    )
                assessments.append(self._assessment(ctx, localised, failing, rec_keys, cond_keys))
            else:
                findings.append(
                    Finding(
                        title="기준 미달 실험 간 공통 조건 없음",
                        body=f"기준 미달 실험({f_codes})이 공유하면서 기준 충족 실험에는 없는 "
                        "조건 값이 없다. 실험별 원인이 다를 수 있다.",
                        severity="info",
                        evidence_keys=rec_keys,
                    )
                )
        elif with_recovery and not failing:
            findings.append(
                Finding(
                    title="프로젝트 전 실험 회수율 기준 충족",
                    body=f"회수율을 측정한 실험 모두 {ctx.criteria.source} 범위 안이다.",
                    severity="info",
                    evidence_keys=[
                        rm.key for e in with_recovery if (rm := ev.get(f"recovery_mean:{e.code}"))
                    ],
                )
            )

        me_sig = ev.prefixed("me_significant:")
        if me_sig:
            solvent = [
                e
                for e in with_recovery
                if "matrix" not in str(e.condition_block.model_dump().get("calibration_type", ""))
            ]
            if solvent:
                findings.append(
                    Finding(
                        title="매트릭스 효과 유의 분석물을 용매 검량선으로 정량 (프로젝트 전반)",
                        body=(
                            "기준을 넘는 매트릭스 효과("
                            + ", ".join(f"{e.label}" for e in me_sig)
                            + ")가 기록되었으나 회수율 실험("
                            + ", ".join(e.code for e in solvent)
                            + ")은 용매 표준 검량선으로 정량했다."
                        ),
                        severity="warning",
                        evidence_keys=[e.key for e in me_sig],
                    )
                )

        decided = [d for d in ctx.decisions.decisions if d.evidence]
        if decided:
            findings.append(
                Finding(
                    title="연구자 결정 이력",
                    body=" ".join(
                        f"P{d.proposal_id}('{d.title}') {d.action}: '{d.rationale}'."
                        for d in decided
                    ),
                    severity="info",
                    evidence_keys=[d.evidence.key for d in decided if d.evidence],
                )
            )
        if not findings:
            findings.append(
                Finding(
                    title="프로젝트 수준 비판 근거 없음",
                    body="회수율이 저장된 실험이 없어 추이를 비판할 수 없다.",
                    severity="info",
                    evidence_keys=[],
                )
            )
        order = {"critical": 0, "warning": 1, "info": 2}
        top = min(findings, key=lambda f: order[f.severity])
        return CritiqueDraft(
            summary=f"'{ctx.project_name}' 프로젝트 수준 검토 — 가장 중요한 지적: {top.title}.",
            findings=findings,
            hypotheses=hypotheses,
            proposals=[],
            assessments=assessments,
        )

    @staticmethod
    def _assessment(
        ctx: ProjectContext,
        localised: list[tuple[str, object]],
        failing: list[ExperimentOut],
        rec_keys: list[str],
        cond_keys: list[str],
    ) -> CriticAssessment:
        labels = ", ".join(_label(k) for k, _v in localised)
        missing: list[MissingControl] = []
        undetermined: list[CriticArgument] = []
        if len(localised) > 1:
            spec = CONTROLS["single_variable"]
            note, dkeys = decision_note(ctx.decisions.for_control(spec.id))
            missing.append(
                MissingControl(
                    id=spec.id,
                    name=spec.name,
                    purpose=spec.purpose,
                    distinguishes=list(spec.distinguishes),
                    evidence_keys=cond_keys + dkeys,
                    decision_note=note,
                )
            )
            undetermined.append(
                CriticArgument(
                    statement=f"{labels}이(가) 같은 실험에서 함께 바뀌어 효과를 분리할 수 없다.",
                    evidence_keys=cond_keys,
                )
            )
        if len(failing) == 1:
            undetermined.append(
                CriticArgument(
                    statement=(
                        f"기준 미달 실험이 {failing[0].code} 하나뿐이라 재현성을 확인할 수 없다."
                    ),
                    evidence_keys=rec_keys,
                )
            )
        return CriticAssessment(
            id="project_recovery_localisation",
            question="프로젝트의 회수율 기준 미달은 어떤 조건 변경과 연관되는가?",
            claim=f"회수율 기준 미달은 {labels} 변경 때문이다",
            verdict="indeterminate" if undetermined else "supported",
            verdict_reason=(
                "연관은 관찰되지만 현재 데이터로 인과를 확정할 수 없다."
                if undetermined
                else "기준 미달이 해당 조건 변경 실험에서만 반복 관찰된다."
            ),
            supporting_evidence=[
                CriticArgument(
                    statement=f"기준 미달은 {labels} 조건 실험에서만 관찰되었다.",
                    evidence_keys=rec_keys + cond_keys,
                )
            ],
            missing_controls=missing,
            undetermined_reasons=undetermined,
        )
