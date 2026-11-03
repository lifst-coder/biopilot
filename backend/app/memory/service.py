"""Memory service: lineage graph, timeline, diff, search and digests.

Depends only on :mod:`app.eln.service` and :mod:`app.core`. Does not compute
analytical numbers (that is Analysis) and does not interpret (that is Partner).
"""

from __future__ import annotations

import difflib
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError
from app.core.llm import LLMGateway, get_gateway
from app.eln import service as eln
from app.eln.schemas import CONDITION_FIELD_LABELS, ExperimentOut, ExperimentSummary
from app.memory.models import ExperimentDigest
from app.memory.schemas import (
    ConditionChange,
    DatasetDiff,
    DigestDraft,
    DigestOut,
    ExperimentDiff,
    GraphEdge,
    GraphNode,
    NoteDiffLine,
    ResearchGraph,
    SearchHit,
    TimelineEntry,
)

# ---------------------------------------------------------------- helpers


def _display(value: Any) -> str:
    """Compact rendering of condition values for digest prose (``10.0`` → ``10``)."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def _conditions(exp: ExperimentOut) -> dict[str, Any]:
    return exp.condition_block.model_dump(exclude_none=True)


def condition_changes(a: ExperimentOut, b: ExperimentOut) -> list[ConditionChange]:
    """Key-by-key comparison of two condition blocks (b relative to a)."""
    ca, cb = _conditions(a), _conditions(b)
    changes: list[ConditionChange] = []
    for key in sorted(set(ca) | set(cb)):
        label = CONDITION_FIELD_LABELS.get(key, key)
        if key not in ca:
            changes.append(ConditionChange(key=key, label=label, change="added", value_b=cb[key]))
        elif key not in cb:
            changes.append(ConditionChange(key=key, label=label, change="removed", value_a=ca[key]))
        elif ca[key] != cb[key]:
            changes.append(
                ConditionChange(
                    key=key, label=label, change="changed", value_a=ca[key], value_b=cb[key]
                )
            )
    return changes


def _summary(exp: ExperimentOut) -> ExperimentSummary:
    return ExperimentSummary.model_validate(exp.model_dump())


def build_graph(experiments: list[ExperimentOut]) -> nx.DiGraph:
    """Directed graph parent → child over ``parent_experiment_id`` links."""
    graph = nx.DiGraph()
    by_id = {e.id: e for e in experiments}
    for e in experiments:
        graph.add_node(e.id)
    for e in experiments:
        if e.parent_experiment_id is not None and e.parent_experiment_id in by_id:
            parent = by_id[e.parent_experiment_id]
            graph.add_edge(
                parent.id, e.id, changed_keys=[c.key for c in condition_changes(parent, e)]
            )
    return graph


# ------------------------------------------------------------------ graph


def get_graph(session: Session, project_id: int) -> ResearchGraph:
    """Lineage graph of a project's experiments."""
    exps = eln.list_experiments_full(session, project_id)
    graph = build_graph(exps)
    roots = sorted(n for n in graph.nodes if graph.in_degree(n) == 0)
    depth: dict[int, int] = {}
    for root in roots:
        for node, d in nx.single_source_shortest_path_length(graph, root).items():
            depth[node] = min(d, depth.get(node, d))
    return ResearchGraph(
        project_id=project_id,
        nodes=[
            GraphNode(
                id=e.id, code=e.code, title=e.title, performed_on=e.performed_on, depth=depth[e.id]
            )
            for e in exps
        ],
        edges=[
            GraphEdge(source=u, target=v, relation="derived_from", changed_keys=d["changed_keys"])
            for u, v, d in sorted(graph.edges(data=True))
        ],
        roots=roots,
    )


def get_lineage(session: Session, experiment_id: int) -> list[ExperimentSummary]:
    """Ancestors from the root down to (and including) the experiment."""
    exp = eln.get_experiment(session, experiment_id)
    exps = eln.list_experiments_full(session, exp.project_id)
    graph = build_graph(exps)
    by_id = {e.id: e for e in exps}
    chain = [experiment_id]
    while preds := list(graph.predecessors(chain[-1])):
        chain.append(preds[0])
    return [_summary(by_id[i]) for i in reversed(chain)]


def get_timeline(session: Session, project_id: int) -> list[TimelineEntry]:
    """Chronological list with what changed versus each experiment's parent."""
    exps = eln.list_experiments_full(session, project_id)
    by_id = {e.id: e for e in exps}
    entries: list[TimelineEntry] = []
    for e in exps:
        parent = by_id.get(e.parent_experiment_id) if e.parent_experiment_id else None
        changed = [c.key for c in condition_changes(parent, e)] if parent else []
        entries.append(
            TimelineEntry(
                experiment_id=e.id,
                code=e.code,
                title=e.title,
                performed_on=e.performed_on,
                parent_experiment_id=e.parent_experiment_id,
                changed_keys_vs_parent=changed,
                dataset_kinds=e.dataset_kinds,
            )
        )
    return entries


# ------------------------------------------------------------------- diff


def diff(session: Session, a_id: int, b_id: int) -> ExperimentDiff:
    """Compare two experiments' originals: conditions, note text, datasets, lineage."""
    a = eln.get_experiment(session, a_id)
    b = eln.get_experiment(session, b_id)
    relation: str = "unrelated"
    common: int | None = None
    if a.id == b.id:
        relation, common = "same", a.id
    elif a.project_id == b.project_id:
        graph = build_graph(eln.list_experiments_full(session, a.project_id))
        anc_a, anc_b = nx.ancestors(graph, a.id), nx.ancestors(graph, b.id)
        if a.id in anc_b:
            relation, common = "a_is_ancestor", a.id
        elif b.id in anc_a:
            relation, common = "b_is_ancestor", b.id
        elif shared := anc_a & anc_b:
            relation = "siblings"
            # nearest common ancestor = the shared ancestor with the most ancestors itself
            common = max(shared, key=lambda n: len(nx.ancestors(graph, n)))
    changes = condition_changes(a, b)
    changed_keys = {c.key for c in changes}
    unchanged = sorted((set(_conditions(a)) & set(_conditions(b))) - changed_keys)

    note_diff: list[NoteDiffLine] = []
    lines_a, lines_b = a.raw_note.splitlines(), b.raw_note.splitlines()
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            note_diff += [NoteDiffLine(op="equal", text=t) for t in lines_a[i1:i2]]
        else:
            note_diff += [NoteDiffLine(op="delete", text=t) for t in lines_a[i1:i2]]
            note_diff += [NoteDiffLine(op="insert", text=t) for t in lines_b[j1:j2]]

    ka, kb = set(a.dataset_kinds), set(b.dataset_kinds)
    return ExperimentDiff(
        a=_summary(a),
        b=_summary(b),
        relation=relation,
        common_ancestor_id=common,
        condition_changes=changes,
        unchanged_keys=unchanged,
        note_diff=note_diff,
        datasets=DatasetDiff(only_a=sorted(ka - kb), only_b=sorted(kb - ka), both=sorted(ka & kb)),
    )


# ----------------------------------------------------------------- search


def _snippet(text: str, needle: str, width: int = 40) -> str:
    idx = text.lower().find(needle.lower())
    start, end = max(0, idx - width), min(len(text), idx + len(needle) + width)
    return (
        ("…" if start else "")
        + text[start:end].replace("\n", " ")
        + ("…" if end < len(text) else "")
    )


def search(session: Session, project_id: int, query: str) -> list[SearchHit]:
    """Case-insensitive substring search over titles, notes, conditions and digests."""
    q = query.strip().lower()
    if not q:
        return []
    hits: list[SearchHit] = []
    exps = eln.list_experiments_full(session, project_id)
    for e in exps:
        if q in e.title.lower():
            hits.append(SearchHit(experiment_id=e.id, code=e.code, field="title", snippet=e.title))
        if q in e.raw_note.lower():
            hits.append(
                SearchHit(
                    experiment_id=e.id,
                    code=e.code,
                    field="raw_note",
                    snippet=_snippet(e.raw_note, q),
                )
            )
        for key, value in _conditions(e).items():
            if q in str(value).lower() or q in key.lower():
                hits.append(
                    SearchHit(
                        experiment_id=e.id,
                        code=e.code,
                        field="condition_block",
                        snippet=f"{CONDITION_FIELD_LABELS.get(key, key)}: {value}",
                    )
                )
    codes = {e.id: e.code for e in exps}
    digests = session.scalars(
        select(ExperimentDigest).where(ExperimentDigest.experiment_id.in_(list(codes)))
    )
    for d in digests:
        if q in d.summary.lower():
            hits.append(
                SearchHit(
                    experiment_id=d.experiment_id,
                    code=codes[d.experiment_id],
                    field="digest",
                    snippet=_snippet(d.summary, q),
                )
            )
    return hits


# ---------------------------------------------------------------- digests


def rules_digest(exp: ExperimentOut, parent: ExperimentOut | None) -> DigestDraft:
    """Deterministic digest: condition summary + bullet lines quoted from the note."""
    cond = _conditions(exp)
    parts = [
        f"{CONDITION_FIELD_LABELS[k]} {_display(cond[k])}"
        for k in ("extraction_solvent", "extraction_time_min", "ph", "cleanup_sorbent", "column")
        if k in cond
    ]
    summary = f"{exp.code} {exp.title}. 주요 조건: " + ", ".join(parts) + "."
    if parent is not None:
        changes = condition_changes(parent, exp)
        if changes:
            changed = "; ".join(
                f"{c.label} {_display(c.value_a)} → {_display(c.value_b)}" for c in changes
            )
            summary += f" {parent.code} 대비 변경: {changed}."
    bullets = [
        line.strip().lstrip("-•").strip()
        for line in exp.raw_note.splitlines()
        if line.strip().startswith(("-", "•"))
    ]
    return DigestDraft(summary=summary, key_points=bullets[:8])


DIGEST_SYSTEM = (
    "You summarise laboratory notebook entries for an analytical chemistry team. "
    "Write in Korean. Only restate what the note and condition block say; never invent "
    "numbers, results or conclusions that are not present in the input."
)


def create_digest(
    session: Session,
    experiment_id: int,
    *,
    gateway: LLMGateway | None = None,
    actor: Actor | None = None,
) -> DigestOut:
    """Create and store a digest (Claude when available, otherwise rules)."""
    gw = gateway or get_gateway()
    exp = eln.get_experiment(session, experiment_id)
    parent = (
        eln.get_experiment(session, exp.parent_experiment_id) if exp.parent_experiment_id else None
    )
    draft: DigestDraft | None = None
    engine = "rules"
    if gw.mode == "claude":
        prompt = (
            f"Experiment {exp.code}: {exp.title}\n\nCondition block (JSON):\n"
            f"{exp.condition_block.model_dump_json(exclude_none=True)}\n\nRaw note:\n{exp.raw_note}"
        )
        draft = gw.generate(system=DIGEST_SYSTEM, prompt=prompt, schema=DigestDraft)
        if draft is not None:
            engine = "claude"
    if draft is None:
        draft = rules_digest(exp, parent)
    row = ExperimentDigest(
        experiment_id=experiment_id,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        summary=draft.summary,
        key_points=draft.key_points,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor or ("ai:claude" if engine == "claude" else "ai:rules"),
        action="memory.digest",
        entity_type="memory.ExperimentDigest",
        entity_id=row.id,
        project_id=exp.project_id,
        payload={"experiment_id": experiment_id, "engine": engine},
    )
    return DigestOut.model_validate(row)


def list_digests(session: Session, experiment_id: int) -> list[DigestOut]:
    """All digests of an experiment, newest first."""
    eln.get_experiment(session, experiment_id)
    rows = session.scalars(
        select(ExperimentDigest)
        .where(ExperimentDigest.experiment_id == experiment_id)
        .order_by(ExperimentDigest.id.desc())
    )
    return [DigestOut.model_validate(r) for r in rows]


def get_digest(session: Session, digest_id: int) -> DigestOut:
    row = session.get(ExperimentDigest, digest_id)
    if row is None:
        raise NotFoundError(f"Digest {digest_id} not found")
    return DigestOut.model_validate(row)
