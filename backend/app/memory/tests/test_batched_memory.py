"""Memory's batched paths (PERFORMANCE.md) give the same answers as the per-item paths.

* FTS: rows are replaced through the indexed ``doc_key → rowid`` map; an index built
  before the map existed is rebuilt; a full rebuild and event-by-event replacement give
  identical rows.
* Fact ports: the ``*_many`` defaults equal per-item calls, merged in provider order.
* Knowledge graph: building with the batch prefetch equals building item by item.
* Failure archive / recall: batched loading equals per-experiment loading.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.eln import service as eln
from app.memory import facts, knowledge_graph, ports, search_index
from app.memory import service as memory
from app.memory.schemas import EntityFacts, FactProvider, KnowledgeNoteCreate, QCFact, ResultFact

FTS, ROWS = search_index.FTS_TABLE, search_index.ROWS_TABLE


def _rows(session: Session) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in session.execute(
            text(f"SELECT rowid, doc_key, text, experiment_id FROM {FTS} ORDER BY rowid")
        )
    ]


def _replace_one_by_one(session: Session, project_id: int) -> None:
    """Event-by-event replacement (the pre-optimisation algorithm) into fresh tables."""
    session.execute(text(f"DROP TABLE IF EXISTS {FTS}"))
    search_index.ensure_table(session)
    for ev in search_index._events(session, project_id, 0):
        doc_key = f"{ev.entity_type}:{ev.entity_id}"
        docs = search_index.documents_for(
            session, ev.entity_type, ev.entity_id, project_id, ev.payload or {}
        )
        search_index._replace(session, {doc_key: docs})


def test_full_rebuild_equals_event_by_event_replacement(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    session.execute(text(f"DROP TABLE IF EXISTS {FTS}"))
    assert search_index.sync(session, pid) > 0
    batched = [r[1:] for r in _rows(session)]
    _replace_one_by_one(session, pid)
    assert [r[1:] for r in _rows(session)] == batched
    assert len(batched) > 50


def test_rows_are_replaced_through_the_indexed_map(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    search_index.sync(session, pid)
    note = memory.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(statement="첫 메모", linked_experiment_ids=[seeded["#018"]]),
    )
    session.commit()
    key = f"memory.KnowledgeNote:{note.id}"
    mapped = session.execute(text(f"SELECT fts_rowid FROM {ROWS} WHERE doc_key = :k"), {"k": key})
    rowids = [r[0] for r in mapped]
    assert len(rowids) == 1
    search_index._replace(session, {key: []})  # an entity whose documents disappeared
    for table in (FTS, ROWS):
        count = text(f"SELECT count(*) FROM {table} WHERE doc_key = :k")
        assert session.execute(count, {"k": key}).scalar_one() == 0
    fts_ids = {r[0] for r in session.execute(text(f"SELECT rowid FROM {FTS}"))}
    map_ids = {r[0] for r in session.execute(text(f"SELECT fts_rowid FROM {ROWS}"))}
    assert fts_ids == map_ids
    plan = session.execute(
        text(f"EXPLAIN QUERY PLAN SELECT fts_rowid FROM {ROWS} WHERE doc_key = 'x'")
    ).all()
    assert any(f"ix_{ROWS}_doc_key" in str(row) for row in plan), plan


def test_index_without_rowid_map_is_rebuilt(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    search_index.sync(session, pid)
    before = [r[1:] for r in _rows(session)]
    session.execute(text(f"DROP TABLE {ROWS}"))  # a database indexed by an older version
    assert search_index.ensure_table(session) is True
    assert _rows(session) == []
    search_index.sync(session, pid)
    assert [r[1:] for r in _rows(session)] == before


class _Single(FactProvider):
    """A provider implementing only the per-item methods."""

    def __init__(self, name: str, tag: str) -> None:
        self.name, self.tag = name, tag

    def results(self, session: Session, experiment_id: int) -> list[ResultFact]:
        return [ResultFact.model_validate(_fact(self.tag, experiment_id))]

    def qc_flags(self, session: Session, experiment_id: int) -> list[QCFact] | None:
        return None if experiment_id % 2 else []

    def describe(
        self, session: Session, ref_type: str, ref_id: int, project_id: int, payload: dict[str, Any]
    ) -> EntityFacts | None:
        if ref_id % 2 and self.tag == "a":
            return None
        return EntityFacts(ref_type=ref_type, ref_id=ref_id, label=f"{self.tag}{payload}")


def _fact(tag: str, experiment_id: int) -> dict[str, Any]:
    src = {"ref_type": "x", "ref_id": experiment_id, "field": "f", "experiment_id": experiment_id}
    return {"metric": tag, "label": tag, "value": 1.0, "source": src}


def test_batched_ports_equal_per_item_calls(
    session: Session, no_providers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ports._providers, "a", _Single("a", "a"))  # removed again on teardown
    monkeypatch.setitem(ports._providers, "b", _Single("b", "b"))
    ids = [1, 2, 3, 4]
    assert ports.results_many(session, ids) == {i: ports.results(session, i) for i in ids}
    assert ports.qc_flags_many(session, ids) == {i: ports.qc_flags(session, i) for i in ids}
    assert ports.facts_many(session, ids) == (
        ports.results_many(session, ids),
        ports.qc_flags_many(session, ids),
    )
    items = [(i, {"p": i}) for i in ids]
    assert ports.describe_many(session, "t", items, 1) == [
        ports.describe(session, "t", i, 1, p) for i, p in items
    ]
    assert [r.metric for r in ports.results_many(session, ids)[1]] == ["a", "b"]


def test_knowledge_graph_prefetch_equals_item_by_item(
    session: Session, seeded: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = seeded["project"]
    knowledge_graph.reset_cache()
    batched = memory.get_knowledge_graph(session, pid)
    knowledge_graph.reset_cache()
    monkeypatch.setattr(knowledge_graph._Builder, "prefetch", lambda self, events: None)
    single = memory.get_knowledge_graph(session, pid)
    knowledge_graph.reset_cache()
    assert batched == single
    assert batched.counts.get("result", 0) > 0 and batched.counts.get("analyte", 0) > 0


def test_failure_archive_and_recall_batches_equal_per_item(
    session: Session, seeded: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = seeded["project"]
    batched = memory.failure_archive(session)
    recall = memory.recall(session, pid, "GCB 회수율")
    exps = eln.list_experiments_full(session, pid)
    assert facts.experiment_vocabs(session, pid, exps) == {
        e.id: facts.experiment_vocab(session, e) for e in exps
    }
    monkeypatch.setattr(
        ports,
        "facts_many",
        lambda s, ids: (
            {i: ports.results(s, i) for i in ids},
            {i: ports.qc_flags(s, i) for i in ids},
        ),
    )
    monkeypatch.setattr(
        memory,
        "experiment_vocabs",
        lambda s, _pid, es: {e.id: facts.experiment_vocab(s, e) for e in es},
    )
    assert memory.failure_archive(session) == batched
    assert batched.failure_count > 0
    assert memory.recall(session, pid, "GCB 회수율") == recall
