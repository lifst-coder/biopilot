"""Memory: lineage, timeline, provider registry."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.memory import service
from app.memory.schemas import FactProvider


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


def test_provider_registry_and_safe_defaults(session: Session, seeded: dict[str, int]) -> None:
    assert service.registered_fact_providers() == ["analysis", "partner"]

    class Dummy(FactProvider):
        name = "dummy"

    service.register_fact_provider(Dummy())
    try:
        assert "dummy" in service.registered_fact_providers()
        d = Dummy()
        assert d.results(session, 1) == [] and d.result_deltas(session, 1, 2) is None
        assert d.qc_flags(session, 1) is None and d.proposals(session, 1) == []
        assert d.describe(session, "x", 1, 1, {}) is None
    finally:
        service.unregister_fact_provider("dummy")
    assert "dummy" not in service.registered_fact_providers()
