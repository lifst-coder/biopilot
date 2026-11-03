"""Research Critic: structured 지지/반대/누락 대조군/대안/확정 불가 output (rules mode)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.partner.context import build_context
from app.partner.engines.critic import assess_recovery_cause, describe_change, fmt, planar_pattern
from app.partner.tests.helpers import with_conditions


def test_024_loss_vs_matrix_effect_is_indeterminate(
    session: Session, seeded: dict[str, int]
) -> None:
    ctx = build_context(session, seeded["#024"])
    a = assess_recovery_cause(ctx)
    assert a is not None and a.id == "recovery_cause"
    assert a.verdict == "indeterminate"
    assert "구분 불가" in a.verdict_reason
    # every section of the critic contract is filled
    assert a.supporting_evidence and a.opposing_evidence and a.undetermined_reasons
    controls = [m.id for m in a.missing_controls]
    assert controls == [
        "pre_post_spike",
        "matrix_matched_calibration",
        "single_variable",
        "is_addition_record",
    ]
    alts = {x.id: x for x in a.alternative_explanations}
    assert set(alts) == {
        "extraction_incomplete",
        "cleanup_adsorption",
        "matrix_suppression",
        "is_correction_bias",
    }
    # GCB planar-analyte pattern supports clean-up adsorption; non-planar drop opposes it
    assert any("GCB" in s.statement for s in alts["cleanup_adsorption"].supporting)
    assert any("평면 구조가 아닌" in s.statement for s in alts["cleanup_adsorption"].opposing)
    # IS deviations only in a subset → IS-correction failure alone is opposed by data
    assert alts["is_correction_bias"].opposing
    # the matrix-effect experiment used another pretreatment (Memory diff)
    assert any("측정된 적이 없다" in r.statement for r in a.undetermined_reasons)
    assert any(arg.basis == "domain_rule" for arg in a.supporting_evidence)
    known = {e.key for e in ctx.evidence.items}
    cited = [k for s in a.supporting_evidence + a.opposing_evidence for k in s.evidence_keys]
    assert cited and set(cited) <= known


def test_no_assessment_when_nothing_to_explain(session: Session, seeded: dict[str, int]) -> None:
    for code in ("#018", "#020", "#021", "#023"):
        assert assess_recovery_cause(build_context(session, seeded[code])) is None


def test_matrix_matched_calibration_changes_verdict(
    session: Session, seeded: dict[str, int]
) -> None:
    ctx = with_conditions(build_context(session, seeded["#024"]), calibration_type="matrix-matched")
    a = assess_recovery_cause(ctx)
    assert a is not None
    ids = [m.id for m in a.missing_controls]
    assert "matrix_matched_calibration" not in ids
    # still confounded by two pretreatment changes
    assert a.verdict == "indeterminate" and "어느 것이" in a.verdict_reason


def test_transferable_matrix_effect_and_single_change_is_supported(
    session: Session, seeded: dict[str, int]
) -> None:
    ctx = build_context(session, seeded["#024"])
    ctx.me_protocol_changes = []  # pretend ME was measured under the #024 protocol
    assert ctx.diff is not None
    ctx.diff = ctx.diff.model_copy(
        update={
            "condition_changes": [
                c for c in ctx.diff.condition_changes if c.key == "cleanup_sorbent"
            ]
        }
    )
    with_conditions(ctx, is_addition_stage="pre-extraction")
    a = assess_recovery_cause(ctx)
    assert a is not None and a.verdict == "supported"
    assert [m.id for m in a.missing_controls] == ["matrix_matched_calibration"]
    assert describe_change(ctx, "cleanup_sorbent").startswith("정제 흡착제")
    assert describe_change(ctx, "ph") == ""


def test_helpers(session: Session, seeded: dict[str, int]) -> None:
    ctx = build_context(session, seeded["#024"])
    assert fmt(None) == "—" and fmt(ctx.evidence.get("recovery_mean")).endswith("%")
    assert planar_pattern(ctx) is not None
    assert planar_pattern(build_context(session, seeded["#022"])) is None
