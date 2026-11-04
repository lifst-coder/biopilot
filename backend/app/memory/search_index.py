"""Full-text search over research memory (MEM-3).

On SQLite the index is an FTS5 virtual table with the ``trigram`` tokenizer, which
gives case-insensitive *substring* matching — important for Korean, where words carry
particles ("회수율이", "회수율은"). Terms shorter than three characters cannot use the
trigram index and fall back to ``LIKE`` on the same table. Ranking uses ``bm25``.

The index is derived data (never an original record). It is synchronised from the
audit log: ``memory_index_state`` stores the last indexed event id per project in the
same transaction as the index rows. Other databases use an in-Python scan of the same
documents.

Reads never write (ISSUES P1-7). :func:`sync` — DDL, watermark upsert, index rows — runs
only from write paths: the commit of any transaction that recorded audit events (same
transaction, :func:`install_sync_on_commit`), application start-up (after seeding) and
``POST /api/memory/search-index/sync``. :func:`search` is read-only: it queries the FTS
rows up to the watermark and scans the audit events *after* the watermark in Python, so
records added since the last sync are still found and their stale index rows are
ignored. Without an FTS table it scans everything in Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, delete, event, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import DatasetOut, ExperimentOut
from app.memory import ports
from app.memory.conditions import conditions, display, label
from app.memory.facts import DatasetVocab, dataset_vocab, dataset_vocabs
from app.memory.models import ExperimentDigest, IndexState, KnowledgeNote
from app.memory.schemas import SearchField, SearchHit, SourceRef

logger = logging.getLogger(__name__)

FTS_TABLE = "memory_search_fts"
#: B-tree side table ``doc_key → FTS rowid``. ``doc_key`` is an UNINDEXED FTS5 column, so
#: ``DELETE … WHERE doc_key = :k`` on the FTS table scans every row (PERFORMANCE.md);
#: deleting by rowid through this indexed map is a point lookup. Created, dropped and
#: rebuilt together with the FTS table (same ``memory_search_fts`` prefix, so Alembic
#: autogenerate ignores both).
ROWS_TABLE = "memory_search_fts_rows"
_DDL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
    "text, doc_key UNINDEXED, project_id UNINDEXED, experiment_id UNINDEXED, "
    "field UNINDEXED, ref_type UNINDEXED, ref_id UNINDEXED, ref_field UNINDEXED, "
    "tokenize='trigram')"
)
_ROWS_DDL = (
    f"CREATE TABLE IF NOT EXISTS {ROWS_TABLE} "
    "(fts_rowid INTEGER PRIMARY KEY, doc_key TEXT NOT NULL)",
    f"CREATE INDEX IF NOT EXISTS ix_{ROWS_TABLE}_doc_key ON {ROWS_TABLE} (doc_key)",
)
MIN_TRIGRAM = 3


@dataclass(frozen=True)
class Doc:
    """One searchable text with its provenance."""

    doc_key: str
    project_id: int
    experiment_id: int
    field: SearchField
    ref_type: str
    ref_id: int
    ref_field: str
    text: str


# --------------------------------------------------------------- documents


@dataclass(frozen=True)
class Prefetched:
    """ELN originals of a batch of events, read with one query per kind (not per event)."""

    experiments: dict[int, ExperimentOut]
    datasets: dict[int, DatasetOut]
    vocabs: dict[int, DatasetVocab]


def prefetch(session: Session, events: list[AuditEvent]) -> Prefetched:
    """Experiments and datasets (+ parsed vocabulary) that ``events`` refer to, batched."""
    exp_ids = sorted({e.entity_id for e in events if e.entity_type == "eln.Experiment"})
    ds_ids = sorted({e.entity_id for e in events if e.entity_type == "eln.Dataset"})
    datasets = eln.get_datasets(session, ds_ids)
    return Prefetched(
        experiments=eln.get_experiments(session, exp_ids),
        datasets=datasets,
        vocabs=dataset_vocabs(session, list(datasets.values())),
    )


def documents_for(
    session: Session,
    entity_type: str,
    entity_id: int,
    project_id: int,
    payload: dict[str, Any],
    pre: Prefetched | None = None,
) -> list[Doc]:
    """Searchable documents contributed by one audited entity.

    ``pre`` (from :func:`prefetch` over the same events) replaces the per-entity reads.
    """
    key = f"{entity_type}:{entity_id}"

    def doc(exp_id: int, fld: SearchField, ref_field: str, body: str) -> Doc:
        return Doc(key, project_id, exp_id, fld, entity_type, entity_id, ref_field, body)

    try:
        if entity_type == "eln.Experiment":
            found = (
                pre.experiments.get(entity_id) if pre else eln.get_experiment(session, entity_id)
            )
            if found is None:
                return []
            exp = found
            out = [
                doc(exp.id, "title", "title", exp.title),
                doc(exp.id, "raw_note", "raw_note", exp.raw_note),
            ]
            for k, v in conditions(exp).items():
                out.append(
                    doc(
                        exp.id,
                        "condition_block",
                        f"condition_block.{k}",
                        f"{label(k)}: {display(v)}",
                    )
                )
            return out
        if entity_type == "eln.Dataset":
            if pre is not None:
                if entity_id not in pre.datasets:
                    return []
                meta, vocab = pre.datasets[entity_id], pre.vocabs[entity_id]
            else:
                meta = eln.get_dataset(session, entity_id)
                vocab = dataset_vocab(session, entity_id, meta)
            parts = []
            if vocab.analytes:
                parts.append("분석물: " + ", ".join(vocab.analytes))
            if vocab.samples:
                parts.append("시료: " + ", ".join(vocab.samples))
            body = f"{meta.filename} ({meta.kind}) " + " · ".join(parts)
            return [doc(meta.experiment_id, "dataset", "content", body)]
        if entity_type == "memory.ExperimentDigest":
            d = session.get(ExperimentDigest, entity_id)
            if d is None:
                return []
            body = d.summary + "\n" + "\n".join(d.key_points)
            return [doc(d.experiment_id, "digest", "summary", body)]
        if entity_type == "memory.KnowledgeNote":
            n = session.get(KnowledgeNote, entity_id)
            if n is None:
                return []
            return [
                doc(e, "knowledge_note", "statement", n.statement) for e in n.linked_experiment_ids
            ]
        if entity_type == "partner.Critique":
            facts = ports.describe(session, entity_type, entity_id, project_id, payload)
            exp_id = (facts.experiment_id if facts else None) or payload.get("experiment_id")
            summary = facts.texts.get("summary") if facts else None
            if exp_id is None or not summary:
                return []
            return [doc(int(exp_id), "critique", "summary", summary)]
    except NotFoundError:
        return []
    return []


# ------------------------------------------------------------------ helpers


def snippet(body: str, needle: str, width: int = 40) -> str:
    """Excerpt of ``body`` around the first case-insensitive ``needle`` occurrence."""
    idx = body.lower().find(needle.lower())
    idx = max(idx, 0)
    start, end = max(0, idx - width), min(len(body), idx + len(needle) + width)
    return (
        ("…" if start else "")
        + body[start:end].replace("\n", " ")
        + ("…" if end < len(body) else "")
    )


def highlights(snip: str, terms: list[str]) -> list[tuple[int, int]]:
    """Merged ``[start, end)`` spans of every term occurrence in ``snip``."""
    low = snip.lower()
    spans: list[tuple[int, int]] = []
    for t in terms:
        pos = low.find(t)
        while pos != -1 and t:
            spans.append((pos, pos + len(t)))
            pos = low.find(t, pos + len(t))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def terms_of(query: str) -> list[str]:
    """Lower-cased whitespace-separated terms (AND semantics)."""
    return [t for t in query.lower().split() if t]


def _hit(doc: Doc, code: str, terms: list[str], score: float) -> SearchHit:
    body = doc.text if doc.field == "title" or doc.field == "condition_block" else None
    snip = body if body is not None else snippet(doc.text, terms[0])
    return SearchHit(
        experiment_id=doc.experiment_id,
        code=code,
        field=doc.field,
        snippet=snip,
        score=round(score, 4),
        highlights=highlights(snip, terms),
        source=SourceRef(
            ref_type=doc.ref_type,
            ref_id=doc.ref_id,
            field=doc.ref_field,
            experiment_id=doc.experiment_id,
        ),
    )


def _events(session: Session, project_id: int, after: int) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id, AuditEvent.id > after)
            .order_by(AuditEvent.id)
        )
    )


# ------------------------------------------------------------------- sqlite


def is_sqlite(session: Session) -> bool:
    """The FTS5 index exists only on SQLite."""
    return session.get_bind().dialect.name == "sqlite"


def table_exists(session: Session, name: str = FTS_TABLE) -> bool:
    """Whether the FTS5 table (or another table) exists (read-only check)."""
    return (
        session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
        ).first()
        is not None
    )


def ensure_table(session: Session) -> bool:
    """Create the FTS5 table and its rowid map if missing (write path only).

    Returns ``True`` if (re)created. Both are (re)built together: an FTS table without
    its map (a database indexed before the map existed) is dropped and rebuilt. A fresh
    table is empty, so every project's watermark is reset with it — otherwise projects
    indexed into a dropped table would stay invisible to FTS.
    """
    if table_exists(session) and table_exists(session, ROWS_TABLE):
        return False
    session.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
    session.execute(text(f"DROP TABLE IF EXISTS {ROWS_TABLE}"))
    session.execute(text(_DDL))
    for ddl in _ROWS_DDL:
        session.execute(text(ddl))
    session.execute(delete(IndexState).where(IndexState.name.like("search:%")))
    return True


_INSERT = text(
    f"INSERT INTO {FTS_TABLE} (rowid, text, doc_key, project_id, experiment_id, field, "
    "ref_type, ref_id, ref_field) VALUES (:rowid, :text, :doc_key, :project_id, "
    ":experiment_id, :field, :ref_type, :ref_id, :ref_field)"
)
_KEYS_CHUNK = 500


def _replace(session: Session, docs: dict[str, list[Doc]]) -> None:
    """Replace the index rows of every entity in ``docs`` (doc_key → its documents).

    Set-based: old rows are deleted by rowid through the indexed map (one statement per
    500 keys) and new rows inserted with ``executemany``; rowids are assigned in ``docs``
    order, so the rows end up as if each entity had been replaced one after the other.
    """
    keys = list(docs)
    for start in range(0, len(keys), _KEYS_CHUNK):
        chunk = {"keys": keys[start : start + _KEYS_CHUNK]}
        session.execute(
            text(
                f"DELETE FROM {FTS_TABLE} WHERE rowid IN "
                f"(SELECT fts_rowid FROM {ROWS_TABLE} WHERE doc_key IN :keys)"
            ).bindparams(bindparam("keys", expanding=True)),
            chunk,
        )
        session.execute(
            text(f"DELETE FROM {ROWS_TABLE} WHERE doc_key IN :keys").bindparams(
                bindparam("keys", expanding=True)
            ),
            chunk,
        )
    rows = [d for key in keys for d in docs[key]]
    if not rows:
        return
    first = int(
        session.execute(
            text(f"SELECT coalesce(max(fts_rowid), 0) + 1 FROM {ROWS_TABLE}")
        ).scalar_one()
    )
    session.execute(
        text(f"INSERT INTO {ROWS_TABLE} (fts_rowid, doc_key) VALUES (:rowid, :doc_key)"),
        [{"rowid": first + i, "doc_key": d.doc_key} for i, d in enumerate(rows)],
    )
    session.execute(_INSERT, [{"rowid": first + i, **d.__dict__} for i, d in enumerate(rows)])


def sync(session: Session, project_id: int) -> int:
    """Index audit events newer than the stored watermark. Returns events applied.

    Writes (DDL, watermark, index rows): called from write paths only — the commit hook
    (:func:`install_sync_on_commit`), start-up and ``POST /search-index/sync`` — never a GET.
    """
    ensure_table(session)
    name = f"search:{project_id}"
    # Upsert first: this write takes SQLite's write lock before the watermark is read,
    # so concurrent first searches neither collide on the row nor index twice.
    session.execute(
        sqlite_insert(IndexState).values(name=name, last_event_id=0).on_conflict_do_nothing()
    )
    state = session.get(IndexState, name, populate_existing=True)
    assert state is not None
    events = _events(session, project_id, state.last_event_id)
    # An entity's rows are replaced on each of its events, so only its *last* event in
    # this batch decides them; earlier ones are skipped (the order of last occurrence is
    # kept, so the rows end up in the same order as replacing them event by event).
    latest: dict[str, AuditEvent] = {}
    for ev in events:
        doc_key = f"{ev.entity_type}:{ev.entity_id}"
        latest.pop(doc_key, None)
        latest[doc_key] = ev
    pre = prefetch(session, list(latest.values()))
    _replace(
        session,
        {
            doc_key: documents_for(
                session, ev.entity_type, ev.entity_id, project_id, ev.payload or {}, pre
            )
            for doc_key, ev in latest.items()
        },
    )
    if events:
        state.last_event_id = events[-1].id
    session.flush()
    return len(events)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _query_sqlite(session: Session, project_id: int, terms: list[str]) -> list[tuple[Doc, float]]:
    long_terms = [t for t in terms if len(t) >= MIN_TRIGRAM]
    short_terms = [t for t in terms if len(t) < MIN_TRIGRAM]
    where = ["project_id = :pid"]
    params: dict[str, Any] = {"pid": project_id}
    score = "0.0"
    if long_terms:
        where.append(f"{FTS_TABLE} MATCH :match")
        params["match"] = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
        score = f"-bm25({FTS_TABLE})"
    for i, t in enumerate(short_terms):
        where.append(f"text LIKE :s{i} ESCAPE '\\'")
        params[f"s{i}"] = _like(t)
    rows = session.execute(
        text(
            "SELECT doc_key, project_id, experiment_id, field, ref_type, ref_id, ref_field, text, "
            f"{score} AS score FROM {FTS_TABLE} WHERE {' AND '.join(where)}"
        ),
        params,
    ).all()
    out: list[tuple[Doc, float]] = []
    for r in rows:
        doc = Doc(r[0], int(r[1]), int(r[2]), r[3], r[4], int(r[5]), r[6], r[7])
        s = float(r[8]) if long_terms else float(sum(r[7].lower().count(t) for t in terms))
        out.append((doc, s))
    return out


def _scan(
    session: Session, project_id: int, events: list[AuditEvent], terms: list[str]
) -> list[tuple[Doc, float]]:
    """In-Python match over the documents of ``events`` (latest event per entity)."""
    latest: dict[str, AuditEvent] = {}
    for ev in events:
        latest[f"{ev.entity_type}:{ev.entity_id}"] = ev
    out: list[tuple[Doc, float]] = []
    pre = prefetch(session, list(latest.values()))
    for ev in latest.values():
        payload = ev.payload or {}
        for d in documents_for(session, ev.entity_type, ev.entity_id, project_id, payload, pre):
            low = d.text.lower()
            if all(t in low for t in terms):
                out.append((d, float(sum(low.count(t) for t in terms))))
    return out


def _query_python(session: Session, project_id: int, terms: list[str]) -> list[tuple[Doc, float]]:
    return _scan(session, project_id, _events(session, project_id, 0), terms)


def indexed_watermark(session: Session, project_id: int) -> int | None:
    """Last audit event id in the FTS index, ``None`` when there is no FTS table (read-only)."""
    if not table_exists(session):
        return None
    state = session.get(IndexState, f"search:{project_id}", populate_existing=True)
    return state.last_event_id if state is not None else 0


def _query_read_only(
    session: Session, project_id: int, terms: list[str]
) -> list[tuple[Doc, float]]:
    """FTS rows up to the watermark + a Python scan of newer events. Never writes."""
    watermark = indexed_watermark(session, project_id)
    if watermark is None:
        return _query_python(session, project_id, terms)
    delta = _events(session, project_id, watermark)
    if not delta:
        return _query_sqlite(session, project_id, terms)
    changed = {f"{ev.entity_type}:{ev.entity_id}" for ev in delta}
    indexed = [
        (d, sc) for d, sc in _query_sqlite(session, project_id, terms) if d.doc_key not in changed
    ]
    return indexed + _scan(session, project_id, delta, terms)


def search(session: Session, project_id: int, query: str, limit: int = 50) -> list[SearchHit]:
    """Ranked hits (highest score first) for all whitespace-separated terms of ``query``."""
    terms = terms_of(query)
    if not terms:
        return []
    codes = {e.id: e.code for e in eln.list_experiments(session, project_id)}
    if is_sqlite(session):
        found = _query_read_only(session, project_id, terms)
    else:  # pragma: no cover - exercised only on non-SQLite deployments
        found = _query_python(session, project_id, terms)
    hits = [_hit(d, codes.get(d.experiment_id, "?"), terms, s) for d, s in found]
    for h in hits:
        h.project_id = project_id
    hits.sort(key=lambda h: (-h.score, h.experiment_id, h.field, h.snippet))
    return hits[:limit]


# ------------------------------------------------------- write-time sync

_DIRTY = "memory.search_index.dirty_projects"


def _after_flush(session: Session, _context: Any) -> None:
    """Remember which projects got new audit events in this transaction."""
    projects = {
        obj.project_id
        for obj in session.new
        if isinstance(obj, AuditEvent) and obj.project_id is not None
    }
    if projects:
        session.info.setdefault(_DIRTY, set()).update(projects)


def _before_commit(session: Session) -> None:
    """Index the projects written in this transaction, inside the same transaction.

    Runs in a SAVEPOINT — safe here because audit rows were already inserted, so the
    outer transaction is open. If indexing fails, the original write still commits and
    the index merely stays behind its watermark; searches cover that gap by scanning.
    """
    if session.new or session.dirty:
        session.flush()  # audit rows added without a flush still mark their project
    projects: set[int] = session.info.pop(_DIRTY, set())
    if not projects or not is_sqlite(session):
        return
    try:
        with session.begin_nested():
            for pid in sorted(projects):
                sync(session, pid)
    except Exception:  # derived data must never block an original record
        logger.exception("search index sync failed; searches will scan pending events")


def _after_rollback(session: Session) -> None:
    session.info.pop(_DIRTY, None)


def install_sync_on_commit() -> None:
    """Index new audit events when the transaction that recorded them commits (idempotent).

    Keeps the FTS index current without any GET writing, so the read path's scan of
    events after the watermark stays empty in normal operation.
    """
    for name, fn in (
        ("after_flush", _after_flush),
        ("before_commit", _before_commit),
        ("after_rollback", _after_rollback),
    ):
        if not event.contains(Session, name, fn):
            event.listen(Session, name, fn)
