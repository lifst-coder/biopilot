"""Next Experiment Designer + Decision History feedback + priority (PAR-8)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.llm import RulesOnlyGateway
from app.partner import service
from app.partner.context import build_context
from app.partner.feedback import classify_rationale, proposal_signature
from app.partner.schemas import DecisionCreate, ProposalChange, ProposalOut

RULES = RulesOnlyGateway()


def _by_template(
    session: Session, seeded: dict[str, int], status: str = "pending"
) -> dict[str, ProposalOut]:
    props = service.list_proposals(
        session, seeded["project"], experiment_id=seeded["#024"], status=status
    )
    return {p.design.template_id: p for p in props if p.design and p.design.template_id}


def _recritique(session: Session, seeded: dict[str, int]):
    crit = service.run_critique(session, seeded["#024"], gateway=RULES)
    props = [service.get_proposal(session, i) for i in crit.proposal_ids]
    return crit, {p.design.template_id: p for p in props if p.design}


def test_designs_have_variables_controls_replicates_and_basis(
    session: Session, seeded: dict[str, int]
) -> None:
    ctx = build_context(session, seeded["#024"])
    reps = ctx.evidence.get("replicates")
    assert reps is not None and reps.label.startswith("#018")
    designs = _by_template(session, seeded)
    assert set(designs) == {"pre_post_spike", "factorial_pretreatment", "dilution_reinjection"}
    for p in designs.values():
        d = p.design
        assert d is not None
        assert d.variables and d.controls and d.measurements and d.expected_outcomes
        assert d.replicates == int(reps.value or 0) and d.replicates_evidence_key == reps.key
        assert seeded["#024"] in d.basis_experiment_ids and seeded["#018"] in d.basis_experiment_ids
        assert d.discriminating_power in {"high", "medium", "low"} and d.power_rationale
    pre = designs["pre_post_spike"].design
    assert pre is not None and seeded["#021"] in pre.basis_experiment_ids
    assert {s for o in pre.expected_outcomes for s in o.supports} >= {
        "matrix_suppression",
        "extraction_incomplete",
    }
    factorial = designs["factorial_pretreatment"]
    assert factorial.base_experiment_id == seeded["#018"]
    assert [v.key for v in factorial.design.variables if v.role == "varied"] == [  # type: ignore[union-attr]
        "cleanup_sorbent",
        "extraction_time_min",
    ]


def test_priority_orders_024_proposals(session: Session, seeded: dict[str, int]) -> None:
    ranked = service.list_proposals(
        session, seeded["project"], experiment_id=seeded["#024"], sort="priority"
    )
    templates = [p.design.template_id for p in ranked if p.design]
    assert templates[-1] == "dilution_reinjection"
    assert set(templates[:2]) == {"pre_post_spike", "factorial_pretreatment"}
    assert ranked[0].priority >= ranked[1].priority > ranked[-1].priority
    for p in ranked:
        assert p.priority == sum(f.points for f in p.priority_factors)
    names = {f.name for f in ranked[0].priority_factors}
    assert {"판별력", "기준 미달 분석물"} <= names
    failing = next(f for f in ranked[0].priority_factors if f.name == "기준 미달 분석물")
    ctx = build_context(session, seeded["#024"])
    assert set(failing.evidence_keys) == {
        ctx.evidence.get("recovery:carbendazim").key,  # type: ignore[union-attr]
        ctx.evidence.get("recovery:thiabendazole").key,  # type: ignore[union-attr]
    }


def test_resource_rejection_yields_alternative_without_repeat(
    session: Session, seeded: dict[str, int]
) -> None:
    pre = _by_template(session, seeded)["pre_post_spike"]
    service.decide(
        session, pre.id, DecisionCreate(action="reject", rationale="블랭크 사과 시료 확보 불가")
    )
    crit, new = _recritique(session, seeded)
    assert "pre_post_spike" not in new
    assert pre.signature not in {p.signature for p in new.values()}
    alt = new["standard_addition"]
    assert alt.supersedes_proposal_ids == [pre.id] and "blank_matrix" not in alt.design.requires  # type: ignore[union-attr]
    # the IS re-analysis also needed a blank → blank-free dilution series instead
    assert (
        "dilution_reinjection" not in new and new["dilution_series"].supersedes_proposal_ids == []
    )
    fb = {f.decision_id: f for f in crit.decision_feedback}
    (entry,) = fb.values()
    assert entry.applied == "alternative_proposed" and entry.reason_category == "resource"
    assert "블랭크 사과 시료 확보 불가" in entry.note
    assert any("이전 연구자 결정 반영" == f.title for f in crit.findings)
    pre_control = next(m for m in crit.assessments[0].missing_controls if m.id == "pre_post_spike")
    assert pre_control.decision_note and "블랭크" in pre_control.decision_note
    history = service.decision_history(session, seeded["project"])
    assert history.entries[0].reflected_in_critique_ids == [crit.id]


def test_workload_rejection_falls_back_to_single_variable(
    session: Session, seeded: dict[str, int]
) -> None:
    factorial = _by_template(session, seeded)["factorial_pretreatment"]
    service.decide(
        session, factorial.id, DecisionCreate(action="reject", rationale="시료 수 부담이 크다")
    )
    crit, _new = _recritique(session, seeded)
    singles = [
        service.get_proposal(session, i)
        for i in crit.proposal_ids
        if service.get_proposal(session, i).title.startswith("단일 변수 실험")
    ]
    assert {p.changes[0].key for p in singles} == {"extraction_time_min", "cleanup_sorbent"}
    assert all(p.supersedes_proposal_ids == [factorial.id] for p in singles)


def test_scientific_rejection_drops_the_control(session: Session, seeded: dict[str, int]) -> None:
    factorial = _by_template(session, seeded)["factorial_pretreatment"]
    service.decide(
        session,
        factorial.id,
        DecisionCreate(action="reject", rationale="두 조건은 함께 바꿀 것이므로 분리는 불필요"),
    )
    crit, new = _recritique(session, seeded)
    assert "factorial_pretreatment" not in new and "single_variable" not in new
    (fb,) = crit.decision_feedback
    assert fb.applied == "noted" and fb.reason_category == "scientific"
    reasons = crit.assessments[0].undetermined_reasons
    assert any(r.basis == "decision" and "불필요" in r.statement for r in reasons)


def test_priority_rejection_defers_template(session: Session, seeded: dict[str, int]) -> None:
    dil = _by_template(session, seeded)["dilution_reinjection"]
    service.decide(
        session, dil.id, DecisionCreate(action="reject", rationale="우선순위 낮음, 추후 진행")
    )
    crit, new = _recritique(session, seeded)
    assert "dilution_reinjection" not in new
    assert new["dilution_series"].supersedes_proposal_ids == [dil.id]
    assert crit.decision_feedback[0].reason_category == "priority"


def test_other_rejection_and_unknown_reason(session: Session, seeded: dict[str, int]) -> None:
    dil = _by_template(session, seeded)["dilution_reinjection"]
    service.decide(session, dil.id, DecisionCreate(action="reject", rationale="그냥 싫다"))
    crit, new = _recritique(session, seeded)
    assert "dilution_reinjection" not in new and "dilution_series" in new
    assert crit.decision_feedback[0].reason_category == "other"


def test_accepted_control_gets_no_alternative(session: Session, seeded: dict[str, int]) -> None:
    pre = _by_template(session, seeded)["pre_post_spike"]
    service.decide(session, pre.id, DecisionCreate(action="accept", rationale="바로 수행"))
    crit, new = _recritique(session, seeded)
    assert "pre_post_spike" not in new and "standard_addition" not in new
    assert crit.decision_feedback[0].applied == "awaiting_result"


def test_modified_proposal_is_not_reproposed(session: Session, seeded: dict[str, int]) -> None:
    pre = _by_template(session, seeded)["pre_post_spike"]
    service.decide(
        session,
        pre.id,
        DecisionCreate(
            action="modify",
            rationale="matrix-matched만",
            modifications=[ProposalChange(key="calibration_type", value="matrix-matched")],
        ),
    )
    _crit, new = _recritique(session, seeded)
    assert "pre_post_spike" not in new


def test_rerun_reuses_pending_proposals(session: Session, seeded: dict[str, int]) -> None:
    (seeded_crit,) = service.list_critiques(session, seeded["#024"])
    again = service.run_critique(session, seeded["#024"], gateway=RULES)
    assert again.proposal_ids == seeded_crit.proposal_ids
    reused, flag = service.get_or_run_critique(session, seeded["#024"], gateway=RULES)
    assert flag and reused.id == again.id


def test_feedback_helpers() -> None:
    a = [ProposalChange(key="a", value=5.0), ProposalChange(key="B", value="X ")]
    b = [ProposalChange(key="b", value="x"), ProposalChange(key="a", value=5)]
    assert proposal_signature(a) == proposal_signature(b)
    assert classify_rationale("블랭크 확보 불가") == ("resource", ["blank_matrix"])
    assert classify_rationale("이미 수행했음")[0] == "already_done"
    assert classify_rationale("의미 없음, 비용도 큼") == ("scientific", ["cost"])
    assert classify_rationale("나중에")[0] == "priority"
    assert classify_rationale("모름") == ("other", [])
