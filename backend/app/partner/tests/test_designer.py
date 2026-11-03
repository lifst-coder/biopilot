"""Next Experiment Designer + Decision History feedback + priority (PAR-8)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.analysis.schemas import CALIBRATION_TYPE_VALUES
from app.core.errors import ValidationFailedError
from app.core.llm import RulesOnlyGateway
from app.partner import service
from app.partner.context import build_context
from app.partner.feedback import classify_rationale, proposal_intent, proposal_signature
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


def test_calibration_type_proposals_stay_in_contract_domain(
    session: Session, seeded: dict[str, int]
) -> None:
    """ISSUES P1-2: every proposed ``calibration_type`` is a value Analysis/ELN accept.

    ``pre_post_spike`` compares the solvent and matrix-matched curves; it quantifies with
    the matrix-matched curve and records the comparison under ``curves_compared``.
    """
    props = service.list_proposals(session, seeded["project"])
    cal = [c for p in props for c in p.changes if c.key == "calibration_type"]
    assert cal and {c.value for c in cal} <= set(CALIBRATION_TYPE_VALUES)
    pre = _by_template(session, seeded)["pre_post_spike"]
    changes = {c.key: c.value for c in pre.changes}
    assert changes["calibration_type"] == "matrix-matched"
    assert changes["curves_compared"] == "solvent + matrix-matched"
    draft = service.experiment_draft(session, pre.id).draft.condition_block.model_dump()
    assert draft["calibration_type"] in CALIBRATION_TYPE_VALUES


def test_modification_outside_calibration_domain_is_rejected(
    session: Session, seeded: dict[str, int]
) -> None:
    pre = _by_template(session, seeded)["pre_post_spike"]
    with pytest.raises(ValidationFailedError, match="calibration_type=solvent"):
        service.decide(
            session,
            pre.id,
            DecisionCreate(
                action="modify",
                rationale="두 곡선 모두",
                modifications=[ProposalChange(key="calibration_type", value="solvent+matrix")],
            ),
        )
    assert service.get_proposal(session, pre.id).status == "pending"


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


# ------------------------------------------------- ISSUES P1-8: feedback limits


def test_rationale_keywords_are_phrases_not_bare_nouns() -> None:
    """A batch or a cost burden is not a sample-workload constraint; a schedule is."""
    # "배치" (a validation batch) and "부담" alone no longer mean "too many samples"
    assert classify_rationale("검증 배치에 이미 배정된 기기다") == ("other", [])
    assert classify_rationale("비용 부담이 크다")[1] == ["cost"]
    assert classify_rationale("한 배치로 돌리기에 작업량이 많다")[1] == ["extra_samples"]
    # instrument schedule → injection constraint (the #OA09 rejection)
    oa09 = "[기기 일정] 공용 LC-MS/MS가 검증 배치에 배정되어 재주입 슬롯이 없다"
    assert classify_rationale(oa09) == ("resource", ["extra_injections"])
    # "already tried and failed" is already_done; a reagent shortage is named
    assert classify_rationale("[이미 시도해 실패] 이미 실패가 확인되었다")[0] == "already_done"
    assert classify_rationale("메탄올 재고가 없어 보류") == ("priority", ["reagent"])


def test_intent_matches_restated_values() -> None:
    a = [ProposalChange(key="cleanup_sorbent", value="PSA 50 mg + GCB 7.5 mg + MgSO4 150 mg")]
    b = [ProposalChange(key="Cleanup Sorbent", value="PSA 50mg + GCB 7.5mg + MgSO₄ 150mg")]
    assert proposal_signature(a) != proposal_signature(b)
    assert proposal_intent(a) == proposal_intent(b)  # spacing, case, subscript ₄ (NFKC)
    c = [ProposalChange(key="cleanup-sorbent", value="PSA 50 mg + C18 50 mg + MgSO4 150 mg")]
    assert proposal_intent(a) != proposal_intent(c)
    t = [ProposalChange(key="extraction_time_min", value=5.0)]
    assert proposal_intent(t) == proposal_intent(
        [ProposalChange(key="extraction_time_min", value="5 min")]
    )
    assert proposal_intent(t) != proposal_intent(
        [ProposalChange(key="extraction_time_min", value="15 min")]
    )


def test_acceptance_settles_the_control_only_for_its_experiment(
    session: Session, seeded: dict[str, int]
) -> None:
    """Accepting pre/post spike for #024 does not silence it for #019 (same symptom)."""
    pre = _by_template(session, seeded)["pre_post_spike"]
    service.decide(session, pre.id, DecisionCreate(action="accept", rationale="바로 수행"))
    _crit, new = _recritique(session, seeded)
    assert "pre_post_spike" not in new  # same experiment: awaiting the result
    other = service.run_critique(session, seeded["#019"], gateway=RULES)
    templates = {
        p.design.template_id
        for p in (service.get_proposal(session, i) for i in other.proposal_ids)
        if p.design
    }
    assert "pre_post_spike" in templates


def test_scientific_dismissal_is_scoped_to_its_experiment(
    session: Session, seeded: dict[str, int]
) -> None:
    pre = _by_template(session, seeded)["pre_post_spike"]
    service.decide(session, pre.id, DecisionCreate(action="reject", rationale="이 실험엔 불필요"))
    _crit, new = _recritique(session, seeded)
    assert "pre_post_spike" not in new and "standard_addition" not in new
    other = service.run_critique(session, seeded["#019"], gateway=RULES)
    templates = {
        p.design.template_id
        for p in (service.get_proposal(session, i) for i in other.proposal_ids)
        if p.design
    }
    # the rejected change set itself is not repeated; the control is still addressed
    assert "pre_post_spike" not in templates and "standard_addition" in templates


# ------------------------------------------- ISSUES P1-9 / P1-10: decision records


def test_decision_actor_and_day(session: Session, seeded: dict[str, int]) -> None:
    from datetime import date, timedelta

    from app.core.audit import list_events
    from app.eln import service as eln

    pre = _by_template(session, seeded)["pre_post_spike"]
    performed = eln.get_experiment(session, seeded["#024"]).performed_on
    with pytest.raises(ValidationFailedError, match="before the experiment"):
        service.decide(
            session,
            pre.id,
            DecisionCreate(action="accept", rationale="r", decided_on=performed - timedelta(1)),
        )
    with pytest.raises(ValidationFailedError, match="in the future"):
        service.decide(
            session,
            pre.id,
            DecisionCreate(action="accept", rationale="r", decided_on=date.today() + timedelta(1)),
        )
    out = service.decide(
        session,
        pre.id,
        DecisionCreate(action="accept", rationale="r", decided_by="김연구", decided_on=performed),
        actor="seed",
    )
    assert out.decision is not None and out.decision.decided_on == performed
    (event,) = list_events(session, entity_type="partner.Decision", entity_id=out.decision.id)
    assert event.actor == "seed"
    assert event.payload["decided_by"] == "김연구"
    assert event.payload["decided_on"] == performed.isoformat()


def test_implementing_changes_drop_design_descriptors(
    session: Session, seeded: dict[str, int]
) -> None:
    by = _by_template(session, seeded)
    pre = {c.key: c.value for c in by["pre_post_spike"].implementing_changes}
    assert pre == {"spike_stage": "pre-extraction + post-extraction"} | {
        "calibration_type": "matrix-matched"
    }
    factorial = by["factorial_pretreatment"]
    assert any(c.key == "design" for c in factorial.changes)
    assert factorial.implementing_changes == []  # factors are levels still to be run
    dil = by["dilution_reinjection"]
    assert {c.key for c in dil.implementing_changes} == {"calibration_type"}  # dilution TBD
    modified = service.decide(
        session,
        dil.id,
        DecisionCreate(
            action="modify",
            rationale="주입량만 줄인다",
            modifications=[ProposalChange(key="injection_volume_ul", value=1)],
        ),
    )
    assert [(c.key, c.value) for c in modified.implementing_changes] == [("injection_volume_ul", 1)]
