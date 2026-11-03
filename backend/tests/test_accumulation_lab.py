"""Lab profile: what only accumulated records show (cross-project recall, records, failures).

The four screens of this feature must work on the lab seed with real data:

1. cross-project recall — #OA06 brought the residue project's PSA d-SPE over;
2. records — the operator difference hidden in #029/#030, the maintenance gap,
   GCB's failure ratio;
3. failure archive — #014 → #015 failed, #016 resolved; GCB failed three times;
4. Critic precedents — #OA06 gets the residue PSA history, #024 gets #OA06.

Numbers are checked as ranges (CLAUDE.md §6).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.analysis import records
from app.memory import service as memory
from app.partner import failures
from app.seed.loader import SeedResult
from app.wiring import install

RES, OA = "residue", "organic_acids"


@pytest.fixture(autouse=True)
def _providers() -> Iterator[None]:
    install()
    yield


def _id(lab: SeedResult, project: str, code: str) -> int:
    return lab.experiment_ids[(project, code)]


def test_cross_project_recall_finds_psa_in_both_projects(
    lab_session: Session, lab: SeedResult
) -> None:
    bundle = memory.recall_all(lab_session, "PSA", limit=50)
    projects = {x.experiment.project_id for x in bundle.experiments}
    assert projects == set(lab.project_ids.values())
    ids = {x.experiment.id for x in bundle.experiments}
    assert _id(lab, OA, "#OA06") in ids and _id(lab, RES, "#001") in ids
    hits = memory.search_all(lab_session, "PSA", limit=200)
    assert {h.project_id for h in hits} == set(lab.project_ids.values())


def test_operator_difference_under_identical_conditions(
    lab_session: Session, lab: SeedResult
) -> None:
    out = records.by_operator(lab_session)
    pair = next(
        p for p in out.pairs if {p.experiment_a.code, p.experiment_b.code} == {"#029", "#030"}
    )
    assert pair.significant is True and pair.p_value is not None and pair.p_value < 0.01
    assert pair.recovery_delta_pct_points is not None
    assert 4.0 <= abs(pair.recovery_delta_pct_points) <= 14.0
    lee = pair.experiment_a if pair.experiment_a.author == "이분석" else pair.experiment_b
    kim = pair.experiment_b if lee is pair.experiment_a else pair.experiment_a
    assert lee.recovery_mean_pct is not None and kim.recovery_mean_pct is not None
    assert lee.recovery_mean_pct > kim.recovery_mean_pct
    # it is the largest same-protocol difference on record
    assert out.pairs[0] is pair or abs(out.pairs[0].recovery_delta_pct_points or 0) <= abs(
        pair.recovery_delta_pct_points
    )


def test_maintenance_gap_spans_both_projects(lab_session: Session, lab: SeedResult) -> None:
    out = records.by_period(lab_session)
    assert len(out.gaps) == 1
    gap = out.gaps[0]
    assert gap.start <= date(2026, 7, 13) and gap.end >= date(2026, 8, 3)
    assert 20 <= gap.days <= 30
    assert {e.project_id for e in gap.before + gap.after} <= set(lab.project_ids.values())
    july = next(m for m in out.months if m.key == "2026-07")
    august = next(m for m in out.months if m.key == "2026-08")
    assert july.experiment_count < august.experiment_count


def test_gcb_fails_more_often_than_the_standard_sorbent(
    lab_session: Session, lab: SeedResult
) -> None:
    out = records.by_condition(lab_session, "cleanup_sorbent", contains="GCB")
    assert out.matched is not None and out.matched.fail_ratio is not None
    standard = max(out.groups, key=lambda g: g.experiment_count)
    assert standard.fail_ratio is not None
    assert out.matched.fail_ratio >= 0.5 > standard.fail_ratio
    gcb75 = next(g for g in out.groups if "GCB 7.5" in g.key)
    assert gcb75.fail_count == gcb75.analyzed_count >= 3


def test_failure_archive_finds_the_reproduction_failure_chain(
    lab_session: Session, lab: SeedResult
) -> None:
    archive = memory.failure_archive(lab_session)
    assert 6 <= archive.failure_count <= 14
    assert sum(t.count for t in archive.types) == archive.failure_count
    chain = next(p for p in archive.patterns if _id(lab, RES, "#014") in p.experiment_ids)
    assert chain.codes == ["#014", "#015"]
    assert chain.resolution is not None and chain.resolution.code == "#016"
    gcb = next(p for p in archive.patterns if _id(lab, RES, "#024") in p.experiment_ids)
    assert {"#024", "#026", "#028"} <= set(gcb.codes)
    assert {"carbendazim", "thiabendazole"} <= set(gcb.shared_analytes)
    no_change = next(t for t in archive.types if t.id == "no_change")
    assert _id(lab, RES, "#014") in no_change.experiment_ids


def test_failure_causes_and_decisions(lab_session: Session, lab: SeedResult) -> None:
    out = failures.failure_archive(lab_session)
    by_id = {e.experiment_id: e for e in out.explanations}
    e014 = by_id[_id(lab, RES, "#014")]
    outside = next(c for c in e014.causes if c.rule == "outside_condition_block")
    assert outside.experiment_ids == [_id(lab, RES, "#010"), _id(lab, RES, "#014")]
    reagent = next(c for c in e014.causes if c.rule == "note_reagent")
    assert reagent.note_excerpt is not None and "lot" in reagent.note_excerpt
    e_oa06 = by_id[_id(lab, OA, "#OA06")]
    elsewhere = next(c for c in e_oa06.causes if c.rule == "used_elsewhere")
    assert set(elsewhere.experiment_ids) <= {
        _id(lab, RES, c) for c in ("#001", "#002", "#003", "#004", "#005")
    }
    actions = [d.action for d in e_oa06.decisions]
    assert actions.count("reject") >= 1 and "accept" in actions
    accepted = next(d for d in e_oa06.decisions if d.action == "accept")
    assert accepted.follow_up is not None and accepted.follow_up.code == "#OA07"
    assert all(d.follow_up is None for d in e_oa06.decisions if d.action == "reject")


def test_oa06_precedents_bring_the_residue_psa_history(
    lab_session: Session, lab: SeedResult
) -> None:
    out = failures.precedents(lab_session, _id(lab, OA, "#OA06"))
    assert out.failed and out.cases
    oa06_date = date(2026, 8, 19)
    assert all(c.experiment.performed_on < oa06_date for c in out.cases)
    usage = next(u for u in out.condition_usage if u.key == "cleanup_sorbent")
    assert usage.project_id == lab.project_ids[RES]
    assert "PSA" in str(usage.value)
    assert usage.fail_count == 0 and usage.experiments
    codes = {x.code for x in usage.experiments}
    assert codes <= {"#001", "#002", "#003"}
    recovered = [x.recovery_mean_pct for x in usage.experiments if x.recovery_mean_pct is not None]
    assert recovered and all(75.0 <= v <= 100.0 for v in recovered)


def test_024_precedents_include_the_organic_acid_sorbent_failure(
    lab_session: Session, lab: SeedResult
) -> None:
    out = failures.precedents(lab_session, _id(lab, RES, "#024"))
    case = next(c for c in out.cases if c.experiment.id == _id(lab, OA, "#OA06"))
    assert any(m.kind == "same_change" and m.key == "cleanup_sorbent" for m in case.matches)
    assert any(d.action == "reject" and "PSA" in d.rationale for d in case.decisions)
    assert len(out.cases) <= failures.MAX_PRECEDENTS


def test_tests_proposal_edges_are_the_seven_follow_ups(
    lab_session: Session, lab: SeedResult
) -> None:
    """ISSUES P1-10: MEM-1 ``tests_proposal`` links each accepted/modified decision to
    the experiment that carried it out (ground truth: ``followed_by`` in the history).

    The links come from Partner's ``implementing_changes``, the decision day and the
    rule that the follow-up itself made the change (not inherited from its parent).
    """
    from app.seed.spec import load_seed_spec

    spec = load_seed_spec("lab")
    expected = {
        (lab.decided_proposal_ids[d.id], _id(lab, d.project, d.followed_by))
        for d in spec.history.decisions
        if d.followed_by
    }
    assert len(expected) == 7
    found = set()
    for pid in lab.project_ids.values():
        graph = memory.get_graph(lab_session, pid, ["tests_proposal"])
        found |= {(e.proposal_id, e.target) for e in graph.edges}
    assert found == expected
