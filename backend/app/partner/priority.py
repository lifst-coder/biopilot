"""Deterministic proposal priority (PAR-8).

The score is a sum of small integer *rule weights*; every count-based term counts
evidence items (e.g. failing analytes cited by the proposal), so the score is fully
explained by ``priority_factors`` and never invents a measurement.

=====================  =====================================================
factor                 points
=====================  =====================================================
판별력                  high 3 · medium 2 · low 1 (design.discriminating_power)
원인 미판정 해소          +2 when the Critic verdict is ``indeterminate`` and the
                       design addresses the loss-vs-matrix controls
교란 해소                +2 when the design separates simultaneously changed
                       conditions the Critic flagged (``single_variable``)
기준 미달 분석물          +1 per failing-analyte evidence item the proposal cites
=====================  =====================================================
"""

from __future__ import annotations

from app.partner.schemas import CriticAssessment, PriorityFactor, ProposalDraft

POWER_POINTS: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
SEPARATING_CONTROLS: frozenset[str] = frozenset({"pre_post_spike", "matrix_matched_calibration"})


def score_proposal(
    draft: ProposalDraft,
    assessment: CriticAssessment | None,
    failing_keys: list[str],
) -> tuple[int, list[PriorityFactor]]:
    """Return ``(priority, factors)`` for one proposal."""
    factors: list[PriorityFactor] = []
    design = draft.design
    if design is not None:
        factors.append(
            PriorityFactor(
                name="판별력",
                points=POWER_POINTS[design.discriminating_power],
                detail=f"예상 판별력 {design.discriminating_power}",
            )
        )
        addressed = set(design.addresses_controls)
        if assessment is not None:
            missing = {m.id: m for m in assessment.missing_controls}
            if assessment.verdict == "indeterminate" and addressed & SEPARATING_CONTROLS & set(
                missing
            ):
                keys = sorted(
                    {
                        k
                        for c in addressed & SEPARATING_CONTROLS
                        if c in missing
                        for k in missing[c].evidence_keys
                    }
                )
                factors.append(
                    PriorityFactor(
                        name="원인 미판정 해소",
                        points=2,
                        detail="전처리 손실 vs 매트릭스 효과 미판정을 해소",
                        evidence_keys=keys,
                    )
                )
            if "single_variable" in addressed and "single_variable" in missing:
                factors.append(
                    PriorityFactor(
                        name="교란 해소",
                        points=2,
                        detail="동시에 바뀐 조건의 효과를 분리",
                        evidence_keys=missing["single_variable"].evidence_keys,
                    )
                )
    cited = [k for k in draft.evidence_keys if k in set(failing_keys)]
    if cited:
        factors.append(
            PriorityFactor(
                name="기준 미달 분석물",
                points=len(cited),
                detail="기준 미달 분석물 근거를 직접 다룸",
                evidence_keys=cited,
            )
        )
    return sum(f.points for f in factors), factors
