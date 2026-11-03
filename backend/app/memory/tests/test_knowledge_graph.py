"""Knowledge graph: node/edge types, incremental refresh, rollback safety, filters."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import DatasetCreate
from app.memory import knowledge_graph as kg
from app.memory import service
from app.memory.schemas import KnowledgeNoteCreate
from app.memory.tests.conftest import make_child
from app.partner import service as partner
from app.partner.schemas import DecisionCreate


def _ids(g: object) -> set[str]:
    return {n.id for n in g.nodes}  # type: ignore[attr-defined]


def _edges(g: object) -> set[tuple[str, str, str]]:
    return {(e.source, e.target, e.relation) for e in g.edges}  # type: ignore[attr-defined]


def test_seed_graph_has_every_node_type_and_link(session: Session, seeded: dict[str, int]) -> None:
    g = service.get_knowledge_graph(session, seeded["project"])
    assert g.refresh.mode == "full" and g.refresh.applied_events > 0
    for t in (
        "experiment",
        "condition",
        "analyte",
        "sample",
        "result",
        "critique",
        "hypothesis",
        "proposal",
    ):
        assert g.counts.get(t, 0) > 0, t
    assert g.counts["experiment"] == 7 and g.counts["analyte"] == 5
    e24 = f"experiment:{seeded['#024']}"
    edges = _edges(g)
    assert (e24, f"experiment:{seeded['#018']}", "derived_from") in edges
    assert (e24, "analyte:carbendazim", "measures") in edges
    assert (e24, "sample:사과 (균질화)", "uses_sample") in edges
    assert any(s == e24 and r == "has_result" for s, _t, r in edges)
    assert any(s == e24 and r == "critiqued_by" for s, _t, r in edges)
    assert any(r == "raises_hypothesis" for _s, _t, r in edges)
    assert any(r == "tests_hypothesis" for _s, _t, r in edges)
    assert any(t == "analyte:carbendazim" and r == "flags" for _s, t, r in edges)
    assert any(r == "shares_conditions" for _s, _t, r in edges)
    labels = {n.id: n.label for n in g.nodes}
    assert labels[e24].startswith("#024")
    sorbent = [n for n in g.nodes if n.type == "condition" and n.attrs["key"] == "cleanup_sorbent"]
    assert len(sorbent) == 2
    cond_edge = next(e for e in g.edges if e.source == e24 and e.relation == "uses_condition")
    assert cond_edge.source_ref is not None and cond_edge.source_ref.ref_id == seeded["#024"]
    derived = next(e for e in g.edges if e.source == e24 and e.relation == "derived_from")
    assert set(derived.attrs["changed_keys"]) == {"extraction_time_min", "cleanup_sorbent"}


def test_incremental_refresh_applies_only_new_events(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    first = service.get_knowledge_graph(session, pid)
    again = service.get_knowledge_graph(session, pid)
    assert again.refresh.mode == "cached" and again.refresh.applied_events == 0

    child = make_child(session, seeded["#024"], "#025", strain="E. coli K-12")
    upd = service.get_knowledge_graph(session, pid)
    assert upd.refresh.mode == "incremental" and upd.refresh.applied_events == 1
    assert upd.refresh.last_event_id > first.refresh.last_event_id
    nid = f"experiment:{child.id}"
    assert nid in _ids(upd) and "strain:e. coli k-12" in _ids(upd)
    assert (nid, f"experiment:{seeded['#024']}", "derived_from") in _edges(upd)

    content = (
        "injection_id,sample_id,analyte,spike_ng_g,analyte_area,is_area\nS-1,X,captan,10,1,1\n"
    )
    eln.create_dataset(
        session, child.id, DatasetCreate(kind="recovery", filename="x.csv", content=content)
    )
    upd2 = service.get_knowledge_graph(session, pid)
    assert upd2.refresh.applied_events == 1
    assert (nid, "analyte:captan", "measures") in _edges(upd2)


def test_rolled_back_events_trigger_rebuild(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    service.get_knowledge_graph(session, pid)
    child = make_child(session, seeded["#018"], "#026")
    assert f"experiment:{child.id}" in _ids(service.get_knowledge_graph(session, pid))
    session.rollback()
    rebuilt = service.get_knowledge_graph(session, pid)
    assert rebuilt.refresh.mode == "full"
    assert f"experiment:{child.id}" not in _ids(rebuilt)


def test_decision_status_and_tests_proposal_are_tracked(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    service.get_knowledge_graph(session, pid)
    proposal = next(p for p in partner.list_proposals(session, pid) if p.id == 3)
    partner.decide(
        session, proposal.id, DecisionCreate(action="accept", rationale="단일 변수 확인")
    )
    g = service.get_knowledge_graph(session, pid)
    assert g.refresh.mode == "incremental"
    decision = next(n for n in g.nodes if n.type == "decision")
    assert decision.label.startswith("accept")
    assert (f"proposal:{proposal.id}", decision.id, "decided") in _edges(g)
    prop_node = next(n for n in g.nodes if n.id == f"proposal:{proposal.id}")
    assert prop_node.attrs["status"] == "accepted"

    follow = make_child(session, proposal.experiment_id, "#027", extraction_time_min=5.0)
    g2 = service.get_knowledge_graph(session, pid)
    assert (f"proposal:{proposal.id}", f"experiment:{follow.id}", "tests_proposal") in _edges(g2)
    lineage = service.get_graph(session, pid, ["tests_proposal"])
    assert any(
        e.relation == "tests_proposal" and e.target == follow.id and e.proposal_id == proposal.id
        for e in lineage.edges
    )


def test_knowledge_note_node(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    note = service.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(
            statement="GCB는 평면 구조 분석물을 흡착한다", linked_experiment_ids=[seeded["#024"]]
        ),
    )
    g = service.get_knowledge_graph(session, pid, types=["note", "experiment"])
    assert (f"note:{note.id}", f"experiment:{seeded['#024']}", "mentions") in _edges(g)
    assert set(g.counts) == {"note", "experiment"}


def test_filters_and_focus(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    only = service.get_knowledge_graph(session, pid, types=["experiment", "analyte"])
    assert {n.type for n in only.nodes} == {"experiment", "analyte"}
    assert {e.relation for e in only.edges} <= {"derived_from", "measures", "shares_conditions"}
    focus = service.get_knowledge_graph(session, pid, focus="analyte:carbendazim", radius=1)
    assert "analyte:carbendazim" in _ids(focus)
    assert all(n.type in ("analyte", "experiment", "result") for n in focus.nodes)
    with pytest.raises(NotFoundError):
        service.get_knowledge_graph(session, pid, focus="experiment:999")
    assert kg.networkx_graph(session, pid).number_of_nodes() == len(
        service.get_knowledge_graph(session, pid).nodes
    )


def test_graph_without_providers_uses_audit_payloads(
    session: Session, seeded: dict[str, int], no_providers: None
) -> None:
    kg.reset_cache()
    g = service.get_knowledge_graph(session, seeded["project"])
    results = [n for n in g.nodes if n.type == "result"]
    assert results and all(n.label.endswith("결과") for n in results)
    hyp = next(n for n in g.nodes if n.type == "hypothesis")
    assert hyp.label.startswith("가설 #")
    assert any(e.relation == "raises_hypothesis" for e in g.edges)
    assert not any(e.relation == "tests_hypothesis" for e in g.edges)


def test_unknown_project_is_404(session: Session, seeded: dict[str, int]) -> None:
    with pytest.raises(NotFoundError):
        service.get_knowledge_graph(session, 999)
