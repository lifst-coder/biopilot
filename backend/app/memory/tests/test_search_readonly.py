"""GET search/recall are read-only; the index is maintained on the write path.

Before the security review every ``GET /search`` and ``/recall`` ran ``CREATE VIRTUAL
TABLE``, upserted ``memory_index_state``, wrote FTS rows and committed. These tests pin
the new contract: start-up builds the index, committing writes extend it, reads never
write — also under concurrent requests on a file-backed database.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.config import Settings
from app.core.db import Database
from app.main import create_app
from app.memory import search_index, service
from app.memory.models import IndexState
from app.memory.schemas import KnowledgeNoteCreate

WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "REPLACE", "ALTER")


@pytest.fixture
def file_client(tmp_path: Path) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'memory.db'}"
    app = create_app(Settings(auto_seed=True, database_url=url), Database(url))
    with TestClient(app) as c:
        yield c


def _engine(client: TestClient) -> Engine:
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    return db.engine


class _WriteRecorder:
    """Collects every write/DDL statement sent to an engine while active."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.writes: list[str] = []
        self._lock = threading.Lock()

    def _on_execute(self, _conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith(WRITE_PREFIXES):
            with self._lock:
                self.writes.append(statement)

    def __enter__(self) -> _WriteRecorder:
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self.engine, "before_cursor_execute", self._on_execute)


def _project(client: TestClient) -> int:
    return int(client.get("/api/eln/projects").json()[0]["id"])


def _watermarks(client: TestClient) -> tuple[int, int]:
    """(stored search watermark, latest audit id) of the first project."""
    pid = _project(client)
    with Session(_engine(client)) as s:
        state = s.get(IndexState, f"search:{pid}")
        latest = s.scalar(select(func.max(AuditEvent.id)).where(AuditEvent.project_id == pid))
    return (state.last_event_id if state else 0), int(latest or 0)


def test_startup_builds_the_index(file_client: TestClient) -> None:
    indexed, latest = _watermarks(file_client)
    assert latest > 0 and indexed == latest


def test_get_search_and_recall_never_write(file_client: TestClient) -> None:
    pid = _project(file_client)
    urls = [
        f"/api/memory/projects/{pid}/search?q=회수율",
        f"/api/memory/projects/{pid}/search?q=회수",  # short term: LIKE path
        f"/api/memory/projects/{pid}/recall?q=GCB 쓴 실험의 회수율은?",
        "/api/memory/search?q=GCB",
        "/api/memory/recall?q=GCB",
    ]
    with _WriteRecorder(_engine(file_client)) as rec:
        for url in urls:
            assert file_client.get(url).status_code == 200
    assert rec.writes == []


def test_reads_do_not_write_even_when_the_index_is_missing(file_client: TestClient) -> None:
    """No lazy CREATE on GET: a dropped index is served by scanning, rebuilt on write."""
    pid = _project(file_client)
    before = file_client.get(f"/api/memory/projects/{pid}/search?q=GCB").json()
    with Session(_engine(file_client)) as s:
        s.execute(text(f"DROP TABLE {search_index.FTS_TABLE}"))
        s.commit()
    with _WriteRecorder(_engine(file_client)) as rec:
        after = file_client.get(f"/api/memory/projects/{pid}/search?q=GCB").json()
    assert rec.writes == []
    assert {(h["experiment_id"], h["field"]) for h in after} == {
        (h["experiment_id"], h["field"]) for h in before
    }
    with Session(_engine(file_client)) as s:  # start-up path rebuilds every project
        assert service.sync_search_index(s).indexed_events > 0
        s.commit()
        assert search_index.table_exists(s)
    indexed, latest = _watermarks(file_client)
    assert indexed == latest


def test_committed_write_is_indexed_in_its_own_transaction(file_client: TestClient) -> None:
    pid = _project(file_client)
    exp = file_client.get(f"/api/eln/projects/{pid}/experiments").json()[0]["id"]
    r = file_client.post(
        f"/api/memory/projects/{pid}/knowledge-notes",
        json={"statement": "흑연화 카본은 평면 분자를 흡착", "linked_experiment_ids": [exp]},
    )
    assert r.status_code == 201
    indexed, latest = _watermarks(file_client)
    assert indexed == latest
    with Session(_engine(file_client)) as s:
        rows = search_index._query_sqlite(s, pid, ["흑연화"])
    assert [d.field for d, _ in rows] == ["knowledge_note"]


def test_uncommitted_writes_are_found_by_scanning(session: Session, seeded: dict[str, int]) -> None:
    """Inside one transaction the newest events are not indexed yet but still found."""
    pid = seeded["project"]
    service.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(statement="미커밋 메모 흑연화", linked_experiment_ids=[seeded["#024"]]),
    )
    assert search_index._query_sqlite(session, pid, ["흑연화"]) == []
    assert [h.field for h in service.search(session, pid, "흑연화")] == ["knowledge_note"]
    session.commit()  # the commit hook indexes it
    assert [d.field for d, _ in search_index._query_sqlite(session, pid, ["흑연화"])] == [
        "knowledge_note"
    ]


def test_failed_index_sync_never_blocks_the_write(
    session: Session, seeded: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = seeded["project"]

    def broken(_session: Session, _pid: int) -> int:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(search_index, "sync", broken)
    note = service.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(statement="동기화 실패 흑연화", linked_experiment_ids=[seeded["#024"]]),
    )
    session.commit()
    assert note.id
    assert [h.field for h in service.search(session, pid, "흑연화")] == ["knowledge_note"]


def test_concurrent_searches_and_recalls_are_consistent(file_client: TestClient) -> None:
    """24 simultaneous GETs: all 200, identical answers, still no writes."""
    pid = _project(file_client)
    urls = [
        f"/api/memory/projects/{pid}/search?q=회수율",
        f"/api/memory/projects/{pid}/recall?q=GCB 회수율",
        "/api/memory/search?q=GCB",
        "/api/memory/recall?q=carbendazim",
    ]
    expected = {u: file_client.get(u).json() for u in urls}
    jobs = urls * 6
    barrier = threading.Barrier(len(jobs))

    def get(url: str) -> tuple[str, int, Any]:
        barrier.wait()
        r = file_client.get(url)
        return url, r.status_code, r.json()

    with _WriteRecorder(_engine(file_client)) as rec, ThreadPoolExecutor(len(jobs)) as pool:
        results = list(pool.map(get, jobs))
    assert rec.writes == []
    for url, status, body in results:
        assert status == 200
        assert body == expected[url]


def test_concurrent_writes_and_searches(file_client: TestClient) -> None:
    """Writers and readers interleaved: no 500, every committed note indexed and found."""
    pid = _project(file_client)
    exp = file_client.get(f"/api/eln/projects/{pid}/experiments").json()[0]["id"]
    n = 6
    barrier = threading.Barrier(2 * n)

    def write(i: int) -> int:
        barrier.wait()
        return file_client.post(
            f"/api/memory/projects/{pid}/knowledge-notes",
            json={"statement": f"동시성 메모 zq{i:02d}", "linked_experiment_ids": [exp]},
        ).status_code

    def read(_i: int) -> int:
        barrier.wait()
        return file_client.get(f"/api/memory/projects/{pid}/search?q=동시성 메모").status_code

    with ThreadPoolExecutor(2 * n) as pool:
        writes = [pool.submit(write, i) for i in range(n)]
        reads = [pool.submit(read, i) for i in range(n)]
        assert [f.result() for f in writes] == [201] * n
        assert [f.result() for f in reads] == [200] * n
    hits = file_client.get(f"/api/memory/projects/{pid}/search?q=동시성 메모&limit=50").json()
    assert sorted(h["snippet"] for h in hits) == [f"동시성 메모 zq{i:02d}" for i in range(n)]
    indexed, latest = _watermarks(file_client)
    assert indexed == latest


@pytest.mark.parametrize(
    "query",
    [
        '" OR 1=1 --',
        "'); DROP TABLE eln_experiments; --",
        'gcb" OR "x',
        "NEAR(gcb 회수율) * ^col:x",
        "100%_x \\ ESCAPE",
        "a b",  # short terms: LIKE path
    ],
)
def test_search_input_is_bound_not_interpolated(
    session: Session, seeded: dict[str, int], query: str
) -> None:
    """FTS5 MATCH and LIKE receive user text only as bound parameters (phrase-quoted)."""
    pid = seeded["project"]
    experiments = session.execute(text("SELECT count(*) FROM eln_experiments")).scalar()
    hits = service.search(session, pid, query)
    assert all(h.project_id == pid for h in hits)
    service.recall(session, pid, query)
    service.search_all(session, query)
    assert session.execute(text("SELECT count(*) FROM eln_experiments")).scalar() == experiments
