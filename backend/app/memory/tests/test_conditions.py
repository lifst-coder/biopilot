"""Condition vectors: similarity, recommendations, history, N-way matrix, MEM-1 edges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailedError
from app.eln import service as eln
from app.memory import service
from app.memory.conditions import key_similarity, proposal_tests, similarity
from app.memory.schemas import ProposalFact


def test_key_similarity_rules() -> None:
    assert key_similarity(10.0, 5.0, 10.0) == 0.5
    assert key_similarity(10.0, 10, None) == 1.0
    assert key_similarity(10.0, 5.0, 0.0) == 0.0
    assert key_similarity("C18 ", "c18", None) == 1.0
    assert key_similarity("C18", "GCB", None) == 0.0
    assert key_similarity(True, 1, None) == 0.0


def test_similarity_is_mean_over_union_of_keys() -> None:
    score, shared = similarity({"a": 1.0, "b": "x"}, {"a": 1.0, "b": "y", "c": 3}, {"a": 0.0})
    assert score == pytest.approx(1 / 3, abs=1e-4) and shared == ["a"]
    assert similarity({}, {}, {}) == (1.0, [])


def test_similar_experiments_ranked_by_condition_vector(
    session: Session, seeded: dict[str, int]
) -> None:
    ranked = service.similar_experiments(session, seeded["#024"], limit=10)
    assert len(ranked) == 6
    assert [r.score for r in ranked] == sorted((r.score for r in ranked), reverse=True)
    top = ranked[0]
    assert top.experiment.code in {"#018", "#021", "#022", "#023"}
    assert {c.key for c in top.differing} == {"extraction_time_min", "cleanup_sorbent"}
    assert 0.8 < top.score < 1.0
    twins = service.similar_experiments(session, seeded["#018"], limit=3)
    assert all(t.score == 1.0 and t.differing == [] for t in twins)
    with pytest.raises(NotFoundError):
        service.similar_experiments(session, 999)


def test_condition_history_shows_extraction_time_10_to_5(
    session: Session, seeded: dict[str, int]
) -> None:
    hist = service.condition_history(session, seeded["project"], "extraction_time_min")
    assert [h.value for h in hist] == [10.0] * 6 + [5.0]
    last = hist[-1]
    assert last.code == "#024" and last.changed_from_previous and last.previous_value == 10.0
    assert not hist[0].changed_from_previous and hist[0].previous_value is None
    assert last.source.field == "condition_block.extraction_time_min"
    assert service.condition_history(session, seeded["project"], "no_such_key") == []


def test_compare_conditions_matrix(session: Session, seeded: dict[str, int]) -> None:
    ids = [seeded[c] for c in ("#018", "#019", "#020", "#021", "#022", "#023", "#024")]
    full = service.compare_conditions(session, ids)
    assert full.experiments[0].code == "#018" and len(full.experiments) == 7
    assert all(len(r.values) == 7 for r in full.rows)
    assert full.rows[0].key == "matrix"  # label order of the ELN contract
    varying = service.compare_conditions(session, ids, varying_only=True)
    assert {r.key for r in varying.rows} == {
        "ph",
        "buffer",
        "column",
        "column_temp_c",
        "extraction_time_min",
        "cleanup_sorbent",
    }
    assert all(r.varying for r in varying.rows) and varying.varying_only
    with pytest.raises(ValidationFailedError):
        service.compare_conditions(session, [])
    with pytest.raises(NotFoundError):
        service.compare_conditions(session, [999])


def test_lineage_graph_mem1_edges(session: Session, seeded: dict[str, int]) -> None:
    default = service.get_graph(session, seeded["project"])
    assert {e.relation for e in default.edges} == {"derived_from"} and len(default.edges) == 6
    shares = service.get_graph(session, seeded["project"], ["shares_conditions"])
    assert shares.edges and all(
        e.relation == "shares_conditions"
        and e.similarity is not None
        and e.similarity >= service.SHARES_CONDITIONS_THRESHOLD
        and e.source < e.target
        for e in shares.edges
    )
    assert service.get_graph(session, seeded["project"], ["tests_proposal"]).edges == []


def test_proposal_tests_matching(session: Session, seeded: dict[str, int]) -> None:
    exps = eln.list_experiments_full(session, seeded["project"])
    base = next(e for e in exps if e.code == "#018")
    # proposed on #018's day; #019 (performed later, pH changed vs #018) tests it
    made = datetime.combine(base.performed_on, datetime.min.time(), tzinfo=UTC)
    p = ProposalFact(id=9, experiment_id=base.id, created_at=made, changes={"ph": "6.5"})
    assert proposal_tests(exps, [p]) == [(9, seeded["#019"])]
    future = p.model_copy(update={"created_at": datetime.now(UTC) + timedelta(days=1)})
    assert proposal_tests(exps, [future]) == []
    # a key absent everywhere is "applied" by every child but changed by none of them:
    # inheriting the parent's state is not testing the proposal
    removed = p.model_copy(update={"changes": {"strain": None}})
    assert proposal_tests(exps, [removed]) == []
    assert proposal_tests(exps, [p.model_copy(update={"changes": {}})]) == []
    bad = p.model_copy(update={"changes": {"ph": "abc"}})
    assert proposal_tests(exps, [bad]) == []
    assert proposal_tests(exps, [p.model_copy(update={"status": "rejected"})]) == []


def test_proposal_tests_uses_decision_day_and_any_parent(
    session: Session, seeded: dict[str, int]
) -> None:
    """ISSUES P1-10: a back-filled decision dates the proposal; lineage is not required.

    #019 changes pH relative to #018. A proposal *on #024* (not #019's parent) decided
    the day before #019 is tested by it; decided the same day or later it is not, even
    though the proposal row was written today.
    """
    exps = eln.list_experiments_full(session, seeded["project"])
    by_code = {e.code: e for e in exps}
    now = datetime.now(UTC)
    p = ProposalFact(
        id=7,
        experiment_id=by_code["#024"].id,
        created_at=now,
        changes={"ph": "6.5"},
        status="accepted",
        decided_on=by_code["#019"].performed_on - timedelta(days=1),
    )
    assert proposal_tests(exps, [p]) == [(7, seeded["#019"])]
    same_day = p.model_copy(update={"decided_on": by_code["#019"].performed_on})
    assert proposal_tests(exps, [same_day]) == []
    assert proposal_tests(exps, [p.model_copy(update={"decided_on": None})]) == []
