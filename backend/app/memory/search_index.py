"""Full-text search over research memory (MEM-3).

On SQLite the index is an FTS5 virtual table with the ``trigram`` tokenizer, which
gives case-insensitive *substring* matching — important for Korean, where words carry
particles ("회수율이", "회수율은"). Terms shorter than three characters cannot use the
trigram index and fall back to ``LIKE`` on the same table. Ranking uses ``bm25``.

The index is derived data (never an original record). It is synchronised from the
audit log: ``memory_index_state`` stores the last indexed event id per project in the
same transaction as the index rows. Other databases use an in-Python scan of the same
documents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.memory import ports
from app.memory.conditions import conditions, display, label
from app.memory.facts import dataset_vocab
from app.memory.models import ExperimentDigest, IndexState, KnowledgeNote
from app.memory.schemas import SearchField, SearchHit, SourceRef

FTS_TABLE = "memory_search_fts"
_DDL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
    "text, doc_key UNINDEXED, project_id UNINDEXED, experiment_id UNINDEXED, "
    "field UNINDEXED, ref_type UNINDEXED, ref_id UNINDEXED, ref_field UNINDEXED, "
    "tokenize='trigram')"
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


def documents_for(
    session: Session, entity_type: str, entity_id: int, project_id: int, payload: dict[str, Any]
) -> list[Doc]:
    """Searchable documents contributed by one audited entity."""
    key = f"{entity_type}:{entity_id}"

    def doc(exp_id: int, fld: SearchField, ref_field: str, body: str) -> Doc:
        return Doc(key, project_id, exp_id, fld, entity_type, entity_id, ref_field, body)

    try:
        if entity_type == "eln.Experiment":
            exp = eln.get_experiment(session, entity_id)
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
            meta = eln.get_dataset(session, entity_id)
            vocab = dataset_vocab(session, entity_id)
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


def _is_sqlite(session: Session) -> bool:
    return session.get_bind().dialect.name == "sqlite"


def sync(session: Session, project_id: int) -> int:
    """Index audit events newer than the stored watermark. Returns events applied."""
    exists = session.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": FTS_TABLE}
    ).first()
    session.execute(text(_DDL))
    name = f"search:{project_id}"
    # Upsert first: this write takes SQLite's write lock before the watermark is read,
    # so concurrent first searches neither collide on the row nor index twice.
    session.execute(
        sqlite_insert(IndexState).values(name=name, last_event_id=0).on_conflict_do_nothing()
    )
    state = session.get(IndexState, name, populate_existing=True)
    assert state is not None
    if not exists:
        state.last_event_id = 0
    events = _events(session, project_id, state.last_event_id)
    for ev in events:
        doc_key = f"{ev.entity_type}:{ev.entity_id}"
        session.execute(text(f"DELETE FROM {FTS_TABLE} WHERE doc_key = :k"), {"k": doc_key})
        for d in documents_for(session, ev.entity_type, ev.entity_id, project_id, ev.payload or {}):
            session.execute(
                text(
                    f"INSERT INTO {FTS_TABLE} (text, doc_key, project_id, experiment_id, field, "
                    "ref_type, ref_id, ref_field) VALUES (:text, :doc_key, :project_id, "
                    ":experiment_id, :field, :ref_type, :ref_id, :ref_field)"
                ),
                d.__dict__,
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


def _query_python(session: Session, project_id: int, terms: list[str]) -> list[tuple[Doc, float]]:
    latest: dict[str, AuditEvent] = {}
    for ev in _events(session, project_id, 0):
        latest[f"{ev.entity_type}:{ev.entity_id}"] = ev
    out: list[tuple[Doc, float]] = []
    for ev in latest.values():
        for d in documents_for(session, ev.entity_type, ev.entity_id, project_id, ev.payload or {}):
            low = d.text.lower()
            if all(t in low for t in terms):
                out.append((d, float(sum(low.count(t) for t in terms))))
    return out


def search(session: Session, project_id: int, query: str, limit: int = 50) -> list[SearchHit]:
    """Ranked hits (highest score first) for all whitespace-separated terms of ``query``."""
    terms = terms_of(query)
    if not terms:
        return []
    codes = {e.id: e.code for e in eln.list_experiments(session, project_id)}
    if _is_sqlite(session):
        sync(session, project_id)
        found = _query_sqlite(session, project_id, terms)
    else:  # pragma: no cover - exercised only on non-SQLite deployments
        found = _query_python(session, project_id, terms)
    hits = [_hit(d, codes.get(d.experiment_id, "?"), terms, s) for d, s in found]
    hits.sort(key=lambda h: (-h.score, h.experiment_id, h.field, h.snippet))
    return hits[:limit]
