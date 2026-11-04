"""Project knowledge graph (NetworkX) built from SQLite and updated incrementally.

Nodes: Experiment ↔ Condition ↔ Analyte/Sample/Strain ↔ Result ↔ Critique ↔
Hypothesis ↔ Proposal ↔ Decision (+ researcher knowledge notes).

Change feed
-----------
Every write in BioPilot appends an :class:`~app.core.audit.AuditEvent` in the same
transaction. The graph therefore keeps a watermark (last applied event id) and, on
each read, applies only the events after it — one entity "contribution" per event.
A contribution owns the edges it created, so re-applying an entity (e.g. a proposal
status change) replaces exactly its own edges. Derived edges (``shares_conditions``,
``tests_proposal``) are recomputed only when experiments or proposals changed.

Labels and links of Analysis/Partner records come from registered fact providers
(:mod:`app.memory.ports`); without them the structure still comes from audit payloads.
The cache lives per database engine and validates its watermark against the audit
table, so a rolled-back transaction triggers a rebuild instead of serving phantoms.
"""

from __future__ import annotations

import threading
import weakref
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import DatasetOut, ExperimentOut
from app.memory import ports
from app.memory.conditions import (
    SAMPLE_KEYS,
    STRAIN_KEYS,
    changed_keys,
    condition_source,
    conditions,
    display,
    label,
    proposal_tests,
    similar_pairs,
)
from app.memory.facts import DatasetVocab, dataset_vocab, dataset_vocabs
from app.memory.models import KnowledgeNote
from app.memory.schemas import (
    EntityFacts,
    GraphRefresh,
    KGEdge,
    KGNode,
    KGNodeType,
    KGRelation,
    KnowledgeGraph,
    ProposalFact,
    SourceRef,
)

#: Experiments whose condition-vector similarity reaches this get a ``shares_conditions`` edge.
SHARES_CONDITIONS_THRESHOLD = 0.9

EdgeKey = tuple[str, str, str]

#: Entity types that contribute to the graph (everything else in the audit log is ignored).
TRACKED = frozenset(
    {
        "eln.Experiment",
        "eln.Dataset",
        "analysis.AnalysisResult",
        "partner.Critique",
        "partner.Hypothesis",
        "partner.Proposal",
        "partner.Decision",
        "memory.KnowledgeNote",
    }
)


#: Entity types whose labels/links come from fact providers (``ports.describe``).
_DESCRIBED = (
    "analysis.AnalysisResult",
    "partner.Critique",
    "partner.Hypothesis",
    "partner.Proposal",
    "partner.Decision",
)


def node_id(kind: str, key: object) -> str:
    """Stable node id ``<type>:<key>`` (free-text keys are case-folded)."""
    text = str(key)
    if kind in ("analyte", "sample", "strain", "condition"):
        text = " ".join(text.split()).casefold()
    return f"{kind}:{text}"


@dataclass
class _State:
    project_id: int
    graph: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)
    owned: dict[str, set[EdgeKey]] = field(default_factory=dict)
    experiments: dict[int, ExperimentOut] = field(default_factory=dict)
    proposals: dict[int, ProposalFact] = field(default_factory=dict)
    last_event_id: int = 0
    last_event_sig: tuple[str, int] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_cache: weakref.WeakKeyDictionary[Engine, dict[int, _State]] = weakref.WeakKeyDictionary()
_cache_lock = threading.Lock()


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


def reset_cache() -> None:
    """Drop every cached graph (tests / admin)."""
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------ graph building


class _Builder:
    """Applies audit events to a :class:`_State`."""

    def __init__(self, session: Session, state: _State) -> None:
        self.session = session
        self.s = state
        self.derived_dirty = False
        # Read in batches by :meth:`prefetch` (one query per entity type, not per event).
        self._prefetched = False
        self._experiments: dict[int, ExperimentOut] = {}
        self._datasets: dict[int, DatasetOut] = {}
        self._vocabs: dict[int, DatasetVocab] = {}
        self._event_facts: dict[int, EntityFacts | None] = {}
        self._event_id: int | None = None

    def prefetch(self, events: list[AuditEvent]) -> None:
        """Read everything the handlers of ``events`` need, one batch per entity type.

        Same records the handlers would read one by one (the database does not change
        during a refresh); facts are fetched per *event*, since a provider may use the
        event's payload.
        """
        by_type: dict[str, list[AuditEvent]] = {}
        for ev in events:
            if ev.entity_type in TRACKED:
                by_type.setdefault(ev.entity_type, []).append(ev)
        exp_ids = sorted({ev.entity_id for ev in by_type.get("eln.Experiment", [])})
        self._experiments = eln.get_experiments(self.session, exp_ids)
        ds_ids = sorted({ev.entity_id for ev in by_type.get("eln.Dataset", [])})
        self._datasets = eln.get_datasets(self.session, ds_ids)
        self._vocabs = dataset_vocabs(self.session, list(self._datasets.values()))
        for ref_type in _DESCRIBED:
            evs = by_type.get(ref_type, [])
            items = [(ev.entity_id, dict(ev.payload or {})) for ev in evs]
            facts = ports.describe_many(self.session, ref_type, items, self.s.project_id)
            self._event_facts.update((ev.id, f) for ev, f in zip(evs, facts, strict=True))
        self._prefetched = True

    # -- primitives
    def node(self, nid: str, kind: KGNodeType, lbl: str, **fields: Any) -> None:
        g = self.s.graph
        attrs = {"type": kind, "label": lbl, **fields}
        if nid in g:
            g.nodes[nid].update(attrs)
        else:
            g.add_node(nid, **attrs)

    def placeholder(self, nid: str, kind: KGNodeType) -> None:
        if nid not in self.s.graph:
            ref_id = int(nid.split(":", 1)[1]) if nid.split(":", 1)[1].isdigit() else None
            self.node(nid, kind, nid, ref_id=ref_id)

    def edge(
        self,
        owner: str,
        u: str,
        v: str,
        relation: KGRelation,
        source_ref: SourceRef | None = None,
        **attrs: Any,
    ) -> None:
        self.s.graph.add_edge(u, v, key=relation, relation=relation, source_ref=source_ref, **attrs)
        self.s.owned.setdefault(owner, set()).add((u, v, relation))

    def clear(self, owner: str) -> None:
        for u, v, k in self.s.owned.pop(owner, set()):
            if self.s.graph.has_edge(u, v, key=k):
                self.s.graph.remove_edge(u, v, key=k)

    # -- event dispatch
    def apply(self, ev: AuditEvent) -> None:
        if ev.entity_type not in TRACKED:
            return
        owner = f"{ev.entity_type}:{ev.entity_id}"
        self.clear(owner)
        handler = getattr(self, "_" + ev.entity_type.replace(".", "_").lower())
        self._event_id = ev.id
        handler(owner, ev.entity_id, dict(ev.payload or {}))

    def _facts(self, ref_type: str, ref_id: int, payload: dict[str, Any]) -> EntityFacts | None:
        if self._event_id in self._event_facts:
            return self._event_facts[self._event_id]
        return ports.describe(self.session, ref_type, ref_id, self.s.project_id, payload)

    def _experiment(self, ref_id: int) -> ExperimentOut | None:
        if self._prefetched:
            return self._experiments.get(ref_id)
        try:
            return eln.get_experiment(self.session, ref_id)
        except NotFoundError:
            return None

    def _dataset(self, ref_id: int) -> tuple[DatasetOut, DatasetVocab] | None:
        if self._prefetched:
            meta = self._datasets.get(ref_id)
            return (meta, self._vocabs[ref_id]) if meta is not None else None
        try:
            meta = eln.get_dataset(self.session, ref_id)
        except NotFoundError:
            return None
        return meta, dataset_vocab(self.session, ref_id, meta)

    def _eln_experiment(self, owner: str, ref_id: int, _payload: dict[str, Any]) -> None:
        exp = self._experiment(ref_id)
        if exp is None:
            return
        self.s.experiments[exp.id] = exp
        self.derived_dirty = True
        eid = node_id("experiment", exp.id)
        self.node(
            eid,
            "experiment",
            f"{exp.code} {exp.title}",
            ref_type="eln.Experiment",
            ref_id=exp.id,
            experiment_id=exp.id,
            attrs={"code": exp.code, "performed_on": exp.performed_on.isoformat()},
        )
        if exp.parent_experiment_id is not None:
            pid = node_id("experiment", exp.parent_experiment_id)
            self.placeholder(pid, "experiment")
            parent = self.s.experiments.get(exp.parent_experiment_id)
            changed = changed_keys(parent, exp) if parent else []
            self.edge(
                owner,
                eid,
                pid,
                "derived_from",
                SourceRef(
                    ref_type="eln.Experiment",
                    ref_id=exp.id,
                    field="parent_experiment_id",
                    experiment_id=exp.id,
                ),
                changed_keys=changed,
            )
        for key, value in conditions(exp).items():
            src = condition_source(exp, key)
            text = display(value)
            if key in SAMPLE_KEYS:
                sid = node_id("sample", text)
                self.node(sid, "sample", text, attrs={"key": key})
                self.edge(owner, eid, sid, "uses_sample", src)
            if key in STRAIN_KEYS:
                tid = node_id("strain", text)
                self.node(tid, "strain", text, attrs={"key": key})
                self.edge(owner, eid, tid, "uses_strain", src)
            cid = node_id("condition", f"{key}={text}")
            self.node(cid, "condition", f"{label(key)}: {text}", attrs={"key": key, "value": value})
            self.edge(owner, eid, cid, "uses_condition", src)

    def _eln_dataset(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        found = self._dataset(ref_id)
        if found is None:
            return
        meta, vocab = found
        eid = node_id("experiment", meta.experiment_id)
        self.placeholder(eid, "experiment")
        for analyte in vocab.analytes:
            aid = node_id("analyte", analyte)
            self.node(aid, "analyte", analyte)
            self.edge(
                owner,
                eid,
                aid,
                "measures",
                SourceRef(
                    ref_type="eln.Dataset",
                    ref_id=ref_id,
                    field="content.analyte",
                    experiment_id=meta.experiment_id,
                ),
                dataset_kind=meta.kind,
            )

    def _analysis_analysisresult(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        facts = self._facts("analysis.AnalysisResult", ref_id, payload)
        exp_id = (facts.experiment_id if facts else None) or payload.get("experiment_id")
        kind = (facts.kind if facts else None) or payload.get("kind") or "result"
        rid = node_id("result", ref_id)
        self.node(
            rid,
            "result",
            facts.label if facts else f"{kind} 결과",
            ref_type="analysis.AnalysisResult",
            ref_id=ref_id,
            experiment_id=exp_id,
            attrs={"kind": kind, "flagged_analytes": facts.flagged_analytes if facts else []},
        )
        if exp_id is not None:
            eid = node_id("experiment", exp_id)
            self.placeholder(eid, "experiment")
            self.edge(
                owner,
                eid,
                rid,
                "has_result",
                SourceRef(
                    ref_type="analysis.AnalysisResult",
                    ref_id=ref_id,
                    field="experiment_id",
                    experiment_id=exp_id,
                ),
            )
        for analyte in facts.flagged_analytes if facts else []:
            aid = node_id("analyte", analyte)
            if aid not in self.s.graph:
                self.node(aid, "analyte", analyte)
            self.edge(
                owner,
                rid,
                aid,
                "flags",
                SourceRef(
                    ref_type="analysis.AnalysisResult",
                    ref_id=ref_id,
                    field="flags",
                    experiment_id=exp_id,
                ),
            )

    def _partner_critique(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        facts = self._facts("partner.Critique", ref_id, payload)
        exp_id = (facts.experiment_id if facts else None) or payload.get("experiment_id")
        cid = node_id("critique", ref_id)
        self.node(
            cid,
            "critique",
            facts.label if facts else f"비판 #{ref_id}",
            ref_type="partner.Critique",
            ref_id=ref_id,
            experiment_id=exp_id,
            attrs={"engine": payload.get("engine")},
        )
        if exp_id is not None:
            eid = node_id("experiment", exp_id)
            self.placeholder(eid, "experiment")
            self.edge(owner, eid, cid, "critiqued_by")

    def _partner_hypothesis(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        facts = self._facts("partner.Hypothesis", ref_id, payload)
        crit = (facts.critique_id if facts else None) or payload.get("critique_id")
        exp_id = facts.experiment_id if facts else None
        hid = node_id("hypothesis", ref_id)
        self.node(
            hid,
            "hypothesis",
            facts.label if facts else f"가설 #{ref_id}",
            ref_type="partner.Hypothesis",
            ref_id=ref_id,
            experiment_id=exp_id,
            attrs={"status": facts.status if facts else None},
        )
        if crit is not None:
            self.placeholder(node_id("critique", crit), "critique")
            self.edge(owner, node_id("critique", crit), hid, "raises_hypothesis")
        elif exp_id is not None:
            self.placeholder(node_id("experiment", exp_id), "experiment")
            self.edge(owner, node_id("experiment", exp_id), hid, "raises_hypothesis")

    def _partner_proposal(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        facts = self._facts("partner.Proposal", ref_id, payload)
        crit = (facts.critique_id if facts else None) or payload.get("critique_id")
        pid = node_id("proposal", ref_id)
        self.node(
            pid,
            "proposal",
            facts.label if facts else f"제안 #{ref_id}",
            ref_type="partner.Proposal",
            ref_id=ref_id,
            experiment_id=facts.experiment_id if facts else None,
            attrs={"status": facts.status if facts else payload.get("to")},
        )
        if crit is not None:
            self.placeholder(node_id("critique", crit), "critique")
            self.edge(owner, node_id("critique", crit), pid, "proposes")
        elif facts and facts.experiment_id is not None:
            self.placeholder(node_id("experiment", facts.experiment_id), "experiment")
            self.edge(owner, node_id("experiment", facts.experiment_id), pid, "proposes")
        if facts and facts.hypothesis_id is not None:
            self.placeholder(node_id("hypothesis", facts.hypothesis_id), "hypothesis")
            self.edge(owner, pid, node_id("hypothesis", facts.hypothesis_id), "tests_hypothesis")
        self.derived_dirty = True

    def _partner_decision(self, owner: str, ref_id: int, payload: dict[str, Any]) -> None:
        facts = self._facts("partner.Decision", ref_id, payload)
        prop = (facts.proposal_id if facts else None) or payload.get("proposal_id")
        did = node_id("decision", ref_id)
        self.node(
            did,
            "decision",
            facts.label if facts else f"결정 #{ref_id}",
            ref_type="partner.Decision",
            ref_id=ref_id,
            experiment_id=facts.experiment_id if facts else None,
            attrs={"status": facts.status if facts else None},
        )
        if prop is not None:
            self.placeholder(node_id("proposal", prop), "proposal")
            self.edge(owner, node_id("proposal", prop), did, "decided")

    def _memory_knowledgenote(self, owner: str, ref_id: int, _payload: dict[str, Any]) -> None:
        note = self.session.get(KnowledgeNote, ref_id)
        if note is None:
            return
        nid = node_id("note", ref_id)
        text = note.statement if len(note.statement) <= 60 else note.statement[:59] + "…"
        self.node(nid, "note", text, ref_type="memory.KnowledgeNote", ref_id=ref_id)
        for exp_id in note.linked_experiment_ids:
            self.placeholder(node_id("experiment", exp_id), "experiment")
            self.edge(
                owner,
                nid,
                node_id("experiment", exp_id),
                "mentions",
                SourceRef(
                    ref_type="memory.KnowledgeNote",
                    ref_id=ref_id,
                    field="linked_experiment_ids",
                    experiment_id=exp_id,
                ),
            )

    # -- derived edges
    def recompute_derived(self) -> None:
        self.clear("derived:shares_conditions")
        exps = list(self.s.experiments.values())
        for a, b, score in similar_pairs(exps, SHARES_CONDITIONS_THRESHOLD):
            self.edge(
                "derived:shares_conditions",
                node_id("experiment", a),
                node_id("experiment", b),
                "shares_conditions",
                similarity=score,
            )
        self.clear("derived:tests_proposal")
        self.s.proposals = {p.id: p for p in ports.proposals(self.session, self.s.project_id)}
        for prop_id, exp_id in proposal_tests(exps, list(self.s.proposals.values())):
            self.placeholder(node_id("proposal", prop_id), "proposal")
            self.edge(
                "derived:tests_proposal",
                node_id("proposal", prop_id),
                node_id("experiment", exp_id),
                "tests_proposal",
            )
        self.derived_dirty = False


# ------------------------------------------------------------------ refresh


def _valid(session: Session, state: _State) -> bool:
    if state.last_event_sig is None:
        return True
    ev = session.get(AuditEvent, state.last_event_id)
    return ev is not None and (ev.entity_type, ev.entity_id) == state.last_event_sig


def _state_for(session: Session, project_id: int) -> tuple[_State, bool]:
    engine = _engine(session)
    with _cache_lock:
        per_engine = _cache.setdefault(engine, {})
        state = per_engine.get(project_id)
        fresh = state is None or not _valid(session, state)
        if fresh:
            state = _State(project_id=project_id)
            per_engine[project_id] = state
    assert state is not None
    return state, fresh


def refresh(session: Session, project_id: int) -> tuple[_State, GraphRefresh]:
    """Bring the cached graph of a project up to date with the audit log."""
    eln.get_project(session, project_id)
    state, fresh = _state_for(session, project_id)
    with state.lock:
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.project_id == project_id, AuditEvent.id > state.last_event_id)
                .order_by(AuditEvent.id)
            )
        )
        builder = _Builder(session, state)
        builder.prefetch(events)
        for ev in events:
            builder.apply(ev)
        if events:
            state.last_event_id = events[-1].id
            state.last_event_sig = (events[-1].entity_type, events[-1].entity_id)
        if builder.derived_dirty or fresh:
            builder.recompute_derived()
        mode = "full" if fresh else ("incremental" if events else "cached")
        return state, GraphRefresh(
            mode=mode,
            applied_events=len(events),
            last_event_id=state.last_event_id,
        )


def _node_out(nid: str, data: dict[str, Any]) -> KGNode:
    return KGNode(
        id=nid,
        type=data["type"],
        label=data["label"],
        ref_type=data.get("ref_type"),
        ref_id=data.get("ref_id"),
        experiment_id=data.get("experiment_id"),
        attrs=data.get("attrs", {}),
    )


def snapshot(
    state: _State,
    refresh_info: GraphRefresh,
    *,
    types: Iterable[str] | None = None,
    focus: str | None = None,
    radius: int = 2,
) -> KnowledgeGraph:
    """Serialise the graph, optionally filtered by node type and/or a focus node."""
    with state.lock:
        g = state.graph
        keep = set(g.nodes)
        if focus is not None:
            if focus not in g:
                raise NotFoundError(f"Graph node {focus} not found")
            keep = set(nx.ego_graph(g.to_undirected(as_view=True), focus, radius=radius).nodes)
        if types:
            wanted = set(types)
            keep = {n for n in keep if g.nodes[n]["type"] in wanted}
        nodes = [_node_out(n, g.nodes[n]) for n in sorted(keep)]
        edges = [
            KGEdge(
                source=u,
                target=v,
                relation=d["relation"],
                source_ref=d.get("source_ref"),
                attrs={k: val for k, val in d.items() if k not in ("relation", "source_ref")},
            )
            for u, v, d in sorted(g.edges(data=True), key=lambda e: (e[0], e[1], e[2]["relation"]))
            if u in keep and v in keep
        ]
        counts = Counter(n.type for n in nodes)
    return KnowledgeGraph(
        project_id=state.project_id,
        nodes=nodes,
        edges=edges,
        counts=dict(sorted(counts.items())),
        refresh=refresh_info,
    )


def networkx_graph(session: Session, project_id: int) -> nx.MultiDiGraph:
    """A copy of the up-to-date graph (for analytics callers inside Memory)."""
    state, _ = refresh(session, project_id)
    with state.lock:
        return state.graph.copy()
