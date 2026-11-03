"""Rules critique engine on the seed scenario, plus the grounding guard."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.partner.context import build_context, ungrounded_numbers, unknown_evidence_keys
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.schemas import CritiqueDraft, Finding

CODES = [f"#0{n}" for n in range(18, 25)]


@pytest.mark.parametrize("code", CODES)
def test_rules_output_is_fully_grounded(
    session: Session, seeded: dict[str, int], code: str
) -> None:
    ctx = build_context(session, seeded[code])
    draft = RulesCritiqueEngine().critique(ctx)
    assert unknown_evidence_keys(draft, ctx) == []
    assert ungrounded_numbers(draft, ctx) == []
    assert draft.findings, "every critique has at least one finding"


def test_024_critique_names_failure_confound_mechanisms_and_is(
    session: Session, seeded: dict[str, int]
) -> None:
    ctx = build_context(session, seeded["#024"])
    draft = RulesCritiqueEngine().critique(ctx)
    titles = [f.title for f in draft.findings]
    assert titles[0] == "회수율 허용 범위 이탈"
    assert draft.findings[0].severity == "critical"
    assert any("원인 분리 불가" in t for t in titles)
    assert any("IS" in t for t in titles)
    statements = " ".join(h.statement for h in draft.hypotheses)
    assert "흡착제" in statements and "추출 시간" in statements
    gcb = next(h for h in draft.hypotheses if "흡착제" in h.statement)
    assert "GCB" in gcb.rationale and "carbendazim" in gcb.rationale
    templates = [p.design.template_id for p in draft.proposals if p.design]
    # the confound is separated by one 2×2 factorial (single-variable designs are its
    # fallback after a rejection — see test_designer.py)
    assert templates == ["pre_post_spike", "factorial_pretreatment", "dilution_reinjection"]
    factorial = draft.proposals[1]
    assert {c.key for c in factorial.changes} >= {
        "factor_extraction_time_min",
        "factor_cleanup_sorbent",
    }
    assert all(p.hypothesis_index is not None for p in draft.proposals)


def test_numbers_in_findings_match_evidence(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#024"])
    mean = ctx.evidence.get("recovery_mean")
    assert mean is not None and mean.value == ctx.metrics.recovery_mean_pct
    draft = RulesCritiqueEngine().critique(ctx)
    assert any(f"{mean.value:.1f}%" in f.body for f in draft.findings)


def test_baseline_passes_and_023_confirms_weighting(
    session: Session, seeded: dict[str, int]
) -> None:
    base = RulesCritiqueEngine().critique(build_context(session, seeded["#018"]))
    assert [f.title for f in base.findings] == ["허용 기준 충족"]
    cal = RulesCritiqueEngine().critique(build_context(session, seeded["#023"]))
    assert any(f.title == "가중 1/x 선택이 데이터와 일치" for f in cal.findings)
    assert cal.proposals == []


def test_grounding_guard_rejects_invented_numbers(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#024"])
    fake = CritiqueDraft(
        summary="회수율이 73.3%로 떨어졌다",
        findings=[Finding(title="t", body="b", severity="info", evidence_keys=["E999"])],
        hypotheses=[],
        proposals=[],
    )
    assert any("73.3" in t for t in ungrounded_numbers(fake, ctx))
    assert unknown_evidence_keys(fake, ctx) == ["E999"]
    # experiment codes and criteria are allowed
    ok = fake.model_copy(update={"summary": "#024는 70–120% 기준 미달", "findings": []})
    assert ungrounded_numbers(ok, ctx) == []
