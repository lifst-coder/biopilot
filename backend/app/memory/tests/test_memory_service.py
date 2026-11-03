"""Memory: lineage graph, diff, timeline, search and digests."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import list_events
from app.memory import service
from app.memory.schemas import DigestDraft


def test_diff_018_vs_024_isolates_the_two_protocol_changes(
    session: Session, seeded: dict[str, int]
) -> None:
    d = service.diff(session, seeded["#018"], seeded["#024"])
    assert d.relation == "a_is_ancestor" and d.common_ancestor_id == seeded["#018"]
    changes = {c.key: (c.value_a, c.value_b) for c in d.condition_changes}
    assert set(changes) == {"extraction_time_min", "cleanup_sorbent"}
    assert changes["extraction_time_min"] == (10.0, 5.0)
    assert "GCB" in str(changes["cleanup_sorbent"][1])
    assert "ph" in d.unchanged_keys
    ops = {line.op for line in d.note_diff}
    assert {"insert", "delete"} <= ops
    assert d.datasets.both == ["calibration", "recovery"]


def test_diff_siblings_and_same(session: Session, seeded: dict[str, int]) -> None:
    sib = service.diff(session, seeded["#019"], seeded["#024"])
    assert sib.relation == "siblings" and sib.common_ancestor_id == seeded["#018"]
    keys = {c.key for c in sib.condition_changes}
    assert {"ph", "buffer", "extraction_time_min", "cleanup_sorbent"} == keys
    same = service.diff(session, seeded["#018"], seeded["#018"])
    assert same.relation == "same" and same.condition_changes == []


def test_graph_lineage_timeline(session: Session, seeded: dict[str, int]) -> None:
    g = service.get_graph(session, seeded["project"])
    assert g.roots == [seeded["#018"]]
    assert len(g.edges) == 6 and all(e.source == seeded["#018"] for e in g.edges)
    assert {n.depth for n in g.nodes} == {0, 1}
    lineage = service.get_lineage(session, seeded["#024"])
    assert [e.code for e in lineage] == ["#018", "#024"]
    tl = {t.code: t for t in service.get_timeline(session, seeded["project"])}
    assert tl["#018"].changed_keys_vs_parent == []
    assert set(tl["#020"].changed_keys_vs_parent) == {"column", "column_temp_c"}


def test_search(session: Session, seeded: dict[str, int]) -> None:
    hits = service.search(session, seeded["project"], "gcb")
    assert {h.code for h in hits} == {"#024"}
    assert {h.field for h in hits} >= {"raw_note", "condition_block"}
    assert service.search(session, seeded["project"], "   ") == []


def test_rules_digest_is_stored_and_audited(session: Session, seeded: dict[str, int]) -> None:
    digests = service.list_digests(session, seeded["#024"])
    assert len(digests) == 1 and digests[0].engine == "rules"
    assert "#018 대비 변경" in digests[0].summary
    assert any("IS" in p for p in digests[0].key_points)
    events = list_events(session, entity_type="memory.ExperimentDigest")
    assert len(events) == 7 and {e.actor for e in events} == {"ai:rules"}


def test_claude_digest_and_fallback(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    def ok(schema: type[BaseModel], _prompt: str) -> BaseModel:
        return DigestDraft(summary="요약", key_points=["관찰"])

    created = service.create_digest(session, seeded["#018"], gateway=fake_gateway_factory(ok))
    assert created.engine == "claude" and created.model == "fake-claude"

    failing = fake_gateway_factory(lambda _s, _p: None)
    fallback = service.create_digest(session, seeded["#018"], gateway=failing)
    assert fallback.engine == "rules" and fallback.model is None
    assert len(failing.calls) == 1
