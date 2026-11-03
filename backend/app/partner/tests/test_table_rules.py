"""PAR-5 table rules: RSD, ME vs solvent curve, pH-sensitive analytes, weighting, IS pattern."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.analysis.schemas import QCFlag
from app.partner import context as context_module
from app.partner.context import EvidenceBook, build_context, ungrounded_numbers
from app.partner.engines import rules as rules_module
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.tests.helpers import with_conditions


def _titles(ctx) -> list[str]:
    draft = RulesCritiqueEngine().critique(ctx)
    assert ungrounded_numbers(draft, ctx) == []
    return [f.title for f in draft.findings]


def test_rsd_rule(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#022"])
    ctx.metrics.flags.append(
        QCFlag(
            code="recovery_rsd_high",
            severity="warning",
            analyte="carbendazim",
            value=23.5,
            threshold_high=20.0,
            context={"spike_ng_g": 10.0},
        )
    )
    ctx.evidence = EvidenceBook()
    context_module._register_extended_evidence(session, ctx)
    assert "회수율 반복성(RSD) 기준 초과" in _titles(ctx)


def test_matrix_effect_rules(session: Session, seeded: dict[str, int]) -> None:
    assert "매트릭스 효과 기준 초과 분석물" in _titles(build_context(session, seeded["#021"]))
    assert "매트릭스 효과 유의 분석물을 용매 검량선으로 정량" in _titles(
        build_context(session, seeded["#022"])
    )
    matched = with_conditions(
        build_context(session, seeded["#022"]), calibration_type="matrix-matched"
    )
    assert "매트릭스 효과 유의 분석물을 용매 검량선으로 정량" not in _titles(matched)


def test_ph_sensitive_rule(session: Session, seeded: dict[str, int]) -> None:
    draft = RulesCritiqueEngine().critique(build_context(session, seeded["#019"]))
    ph = next(f for f in draft.findings if f.title == "pH 민감 분석물 영향 점검")
    assert "carbendazim" in ph.body and ph.severity == "info"


def test_weighting_proposal(
    session: Session, seeded: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rules_module, "_calibration_is_replicated", lambda _ctx: True)
    ctx = with_conditions(build_context(session, seeded["#024"]), calibration_weighting="none")
    draft = RulesCritiqueEngine().critique(ctx)
    assert any(f.title.startswith("가중 ") and "줄임" in f.title for f in draft.findings)
    weighting = [p for p in draft.proposals if p.title.startswith("검량선 가중을")]
    assert (
        weighting
        and weighting[0].design
        and weighting[0].design.template_id == "calibration_weighting"
    )
    assert ungrounded_numbers(draft, ctx) == []


def test_calibration_threshold_rules(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#024"])
    r2, back = ctx.evidence.get("min_r2"), ctx.evidence.get("max_back_calc")
    assert r2 and back
    r2.value, back.value = 0.95, 25.0
    titles = _titles(ctx)
    assert "검량선 직선성 미흡" in titles and "검량선 역산 정확도 기준 초과" in titles


def test_systematic_is_pattern(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#024"])
    total = ctx.evidence.get("is_total")
    flagged = ctx.evidence.get("is_flagged")
    assert total and flagged
    flagged.value = total.value
    draft = RulesCritiqueEngine().critique(ctx)
    is_f = next(f for f in draft.findings if f.title == "내부표준(IS) 응답 억제")
    assert "체계적 원인" in is_f.body
