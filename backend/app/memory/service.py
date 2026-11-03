"""Memory service: lineage & knowledge graph, timeline, diff, search/recall, digests.

Depends only on :mod:`app.eln.service` and :mod:`app.core`. Memory never computes
analytical numbers (that is Analysis) and never interprets (that is Partner): stored
results and QC flags of higher layers reach Memory through registered
:class:`~app.memory.schemas.FactProvider` ports (see :func:`register_fact_provider`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.grounding import ungrounded_numbers
from app.core.llm import LLMGateway, get_gateway
from app.eln import service as eln
from app.eln.schemas import CONDITION_FIELD_LABELS, ExperimentOut, ExperimentSummary
from app.memory import failures as failure_archive_mod
from app.memory import knowledge_graph as kg
from app.memory import ports, search_index
from app.memory.conditions import (
    condition_changes,
    condition_source,
    conditions,
    display,
    label,
    numeric_ranges,
    proposal_tests,
    protocol_id,
    similar_pairs,
    similarity,
)
from app.memory.facts import ExperimentVocab, experiment_vocab
from app.memory.models import ExperimentDigest, KnowledgeNote
from app.memory.schemas import (
    ConditionHistoryEntry,
    ConditionMatrix,
    ConditionMatrixRow,
    DatasetDiff,
    DigestDraft,
    DigestOut,
    EvidenceFragment,
    ExperimentDiff,
    Facet,
    FactProvider,
    FailureArchive,
    GraphEdge,
    GraphNode,
    GraphRelation,
    KnowledgeGraph,
    KnowledgeNoteCreate,
    KnowledgeNoteList,
    KnowledgeNoteOut,
    MatchedTerm,
    MemoryAnswer,
    MemoryAnswerDraft,
    MemoryAskRequest,
    ProtocolGroup,
    QCChange,
    QCFact,
    RecallBundle,
    RecallExperiment,
    ResearchGraph,
    ResultFact,
    SearchHit,
    SimilarExperiment,
    SourceRef,
    TimelineEntry,
)
from app.memory.textdiff import note_diff

__all__ = [
    "SHARES_CONDITIONS_THRESHOLD",
    "ask",
    "build_graph",
    "compare_conditions",
    "condition_changes",
    "condition_history",
    "create_digest",
    "create_knowledge_note",
    "diff",
    "digest_fingerprint",
    "failure_archive",
    "get_digest",
    "get_graph",
    "get_knowledge_graph",
    "get_lineage",
    "get_timeline",
    "list_digests",
    "list_knowledge_notes",
    "recall",
    "recall_all",
    "register_fact_provider",
    "registered_fact_providers",
    "rules_digest",
    "search",
    "search_all",
    "similar_experiments",
    "unregister_fact_provider",
]

SHARES_CONDITIONS_THRESHOLD = kg.SHARES_CONDITIONS_THRESHOLD

# ------------------------------------------------------------- fact ports


def register_fact_provider(provider: FactProvider) -> None:
    """Register a higher-layer fact provider (called once at the composition root)."""
    ports.register(provider)


def unregister_fact_provider(name: str) -> None:
    """Remove a registered provider by name (tests)."""
    ports.unregister(name)


def registered_fact_providers() -> list[str]:
    """Names of registered providers."""
    return ports.registered()


# ---------------------------------------------------------------- helpers


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

ALL_RELATIONS: tuple[GraphRelation, ...] = ("derived_from", "shares_conditions", "tests_proposal")
DEFAULT_RELATIONS: tuple[GraphRelation, ...] = ("derived_from",)


def get_graph(
    session: Session, project_id: int, relations: Iterable[GraphRelation] | None = None
) -> ResearchGraph:
    """Experiment graph: lineage plus opt-in ``shares_conditions`` / ``tests_proposal`` edges.

    ``relations`` defaults to ``["derived_from"]`` so existing consumers keep seeing
    exactly the lineage edges; pass the other relations (MEM-1) explicitly.
    """
    wanted = set(relations or DEFAULT_RELATIONS)
    exps = eln.list_experiments_full(session, project_id)
    graph = build_graph(exps)
    roots = sorted(n for n in graph.nodes if graph.in_degree(n) == 0)
    depth: dict[int, int] = {}
    for root in roots:
        for node, d in nx.single_source_shortest_path_length(graph, root).items():
            depth[node] = min(d, depth.get(node, d))
    edges: list[GraphEdge] = []
    if "derived_from" in wanted:
        edges += [
            GraphEdge(source=u, target=v, relation="derived_from", changed_keys=d["changed_keys"])
            for u, v, d in sorted(graph.edges(data=True))
        ]
    by_id = {e.id: e for e in exps}
    if "shares_conditions" in wanted:
        for a, b, score in similar_pairs(exps, SHARES_CONDITIONS_THRESHOLD):
            edges.append(
                GraphEdge(
                    source=a,
                    target=b,
                    relation="shares_conditions",
                    changed_keys=[c.key for c in condition_changes(by_id[a], by_id[b])],
                    similarity=score,
                )
            )
    if "tests_proposal" in wanted:
        for prop_id, exp_id in proposal_tests(exps, ports.proposals(session, project_id)):
            exp = by_id[exp_id]
            assert exp.parent_experiment_id is not None
            edges.append(
                GraphEdge(
                    source=exp.parent_experiment_id,
                    target=exp_id,
                    relation="tests_proposal",
                    changed_keys=[
                        c.key for c in condition_changes(by_id[exp.parent_experiment_id], exp)
                    ],
                    proposal_id=prop_id,
                )
            )
    return ResearchGraph(
        project_id=project_id,
        nodes=[
            GraphNode(
                id=e.id, code=e.code, title=e.title, performed_on=e.performed_on, depth=depth[e.id]
            )
            for e in exps
        ],
        edges=edges,
        roots=roots,
    )


def get_knowledge_graph(
    session: Session,
    project_id: int,
    *,
    types: Iterable[str] | None = None,
    focus: str | None = None,
    radius: int = 2,
) -> KnowledgeGraph:
    """Knowledge graph of a project, incrementally refreshed from the audit log."""
    state, info = kg.refresh(session, project_id)
    return kg.snapshot(state, info, types=types, focus=focus, radius=radius)


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


# ------------------------------------------------------------- conditions


def condition_history(session: Session, project_id: int, key: str) -> list[ConditionHistoryEntry]:
    """Chronological values of one condition key across a project (MEM-2)."""
    out: list[ConditionHistoryEntry] = []
    previous: Any = None
    for e in eln.list_experiments_full(session, project_id):
        cond = conditions(e)
        if key not in cond:
            continue
        value = cond[key]
        out.append(
            ConditionHistoryEntry(
                experiment_id=e.id,
                code=e.code,
                performed_on=e.performed_on,
                value=value,
                changed_from_previous=bool(out) and value != previous,
                previous_value=previous if out else None,
                source=condition_source(e, key),
            )
        )
        previous = value
    return out


def _key_order(keys: Iterable[str]) -> list[str]:
    known = list(CONDITION_FIELD_LABELS)
    return sorted(keys, key=lambda k: (known.index(k) if k in known else len(known), k))


def compare_conditions(
    session: Session, experiment_ids: list[int], *, varying_only: bool = False
) -> ConditionMatrix:
    """Key × experiment matrix of condition values (MEM-5)."""
    if not experiment_ids:
        raise ValidationFailedError("at least one experiment id is required")
    exps = [eln.get_experiment(session, i) for i in experiment_ids]
    conds = [conditions(e) for e in exps]
    rows: list[ConditionMatrixRow] = []
    for key in _key_order({k for c in conds for k in c}):
        values = [c.get(key) for c in conds]
        varying = len({json.dumps(v, sort_keys=True, default=str) for v in values}) > 1
        if varying_only and not varying:
            continue
        rows.append(ConditionMatrixRow(key=key, label=label(key), values=values, varying=varying))
    return ConditionMatrix(
        experiments=[_summary(e) for e in exps], rows=rows, varying_only=varying_only
    )


def similar_experiments(
    session: Session, experiment_id: int, limit: int = 5
) -> list[SimilarExperiment]:
    """Experiments ranked by condition-vector similarity to ``experiment_id``."""
    target = eln.get_experiment(session, experiment_id)
    exps = eln.list_experiments_full(session, target.project_id)
    ranges = numeric_ranges(exps)
    base = conditions(target)
    ranked: list[SimilarExperiment] = []
    for e in exps:
        if e.id == target.id:
            continue
        score, shared = similarity(base, conditions(e), ranges)
        ranked.append(
            SimilarExperiment(
                experiment=_summary(e),
                score=score,
                shared_keys=shared,
                differing=condition_changes(target, e),
            )
        )
    ranked.sort(key=lambda s: (-s.score, s.experiment.performed_on, s.experiment.id))
    return ranked[:limit]


# ------------------------------------------------------------------- diff


def _relation(a: ExperimentOut, b: ExperimentOut, session: Session) -> tuple[str, int | None]:
    if a.id == b.id:
        return "same", a.id
    if a.project_id != b.project_id:
        return "unrelated", None
    graph = build_graph(eln.list_experiments_full(session, a.project_id))
    anc_a, anc_b = nx.ancestors(graph, a.id), nx.ancestors(graph, b.id)
    if a.id in anc_b:
        return "a_is_ancestor", a.id
    if b.id in anc_a:
        return "b_is_ancestor", b.id
    if shared := anc_a & anc_b:
        # nearest common ancestor = the shared ancestor with the most ancestors itself
        return "siblings", max(shared, key=lambda n: len(nx.ancestors(graph, n)))
    return "unrelated", None


def _qc_key(f: QCFact) -> tuple[str, str, str]:
    return f.code, f.analyte or "", json.dumps(f.context, sort_keys=True, default=str)


def qc_changes(flags_a: list[QCFact], flags_b: list[QCFact]) -> list[QCChange]:
    """Set comparison of QC flags (appeared in b / resolved in b / persisting)."""
    ka = {_qc_key(f): f for f in flags_a}
    kb = {_qc_key(f): f for f in flags_b}
    out: list[QCChange] = []
    for key in sorted(set(ka) | set(kb)):
        fa, fb = ka.get(key), kb.get(key)
        ref = fb or fa
        assert ref is not None
        change = "persisting" if fa and fb else ("appeared" if fb else "resolved")
        out.append(
            QCChange(
                code=ref.code,
                analyte=ref.analyte,
                context=ref.context,
                change=change,
                severity=ref.severity,
                value_a=fa.value if fa else None,
                value_b=fb.value if fb else None,
                sources=[f.source for f in (fa, fb) if f is not None],
            )
        )
    order = {"appeared": 0, "resolved": 1, "persisting": 2}
    out.sort(key=lambda c: (order[c.change], c.code, c.analyte or ""))
    return out


INFO_SEVERITY = "info"


def split_info_changes(changes: list[QCChange]) -> tuple[list[QCChange], list[QCChange]]:
    """Split QC changes into (warning/critical, informational) by the flag's severity.

    Informational flags (``severity == "info"``) are context, not QC failures: they must
    not appear as failures that "appeared" or were "resolved" between two experiments.
    """
    qc = [c for c in changes if c.severity != INFO_SEVERITY]
    info = [c for c in changes if c.severity == INFO_SEVERITY]
    return qc, info


def diff(session: Session, a_id: int, b_id: int) -> ExperimentDiff:
    """Deterministic diff of two experiments with provenance on every item.

    Conditions and note text come from ELN originals; result values/deltas and QC
    flags come from stored Analysis results via the fact port (no arithmetic here).
    """
    a = eln.get_experiment(session, a_id)
    b = eln.get_experiment(session, b_id)
    relation, common = _relation(a, b, session)
    changes = condition_changes(a, b)
    changed_keys = {c.key for c in changes}
    unchanged = sorted((set(conditions(a)) & set(conditions(b))) - changed_keys)
    ka, kb = set(a.dataset_kinds), set(b.dataset_kinds)
    deltas = ports.result_deltas(session, a.id, b.id)
    flags_a, flags_b = ports.qc_flags(session, a.id), ports.qc_flags(session, b.id)
    have_flags = flags_a is not None and flags_b is not None
    qc, qc_info = (
        split_info_changes(qc_changes(flags_a or [], flags_b or [])) if have_flags else ([], [])
    )
    return ExperimentDiff(
        a=_summary(a),
        b=_summary(b),
        relation=relation,
        common_ancestor_id=common,
        condition_changes=changes,
        unchanged_keys=unchanged,
        note_diff=note_diff(a.raw_note, b.raw_note),
        datasets=DatasetDiff(only_a=sorted(ka - kb), only_b=sorted(kb - ka), both=sorted(ka & kb)),
        results_available=deltas is not None,
        result_changes=deltas or [],
        qc_changes=qc,
        qc_info_changes=qc_info,
    )


# ----------------------------------------------------------------- search


def search(session: Session, project_id: int, query: str, limit: int = 50) -> list[SearchHit]:
    """Ranked full-text search over notes, conditions, datasets, digests, critiques, notes."""
    return search_index.search(session, project_id, query, limit)


def _project_ids(session: Session, project_ids: Iterable[int] | None) -> list[int]:
    known = [p.id for p in eln.list_projects(session)]
    if project_ids is None:
        return known
    wanted = set(project_ids)
    missing = sorted(wanted - set(known))
    if missing:
        raise NotFoundError(f"project {missing[0]} not found")
    return [p for p in known if p in wanted]


def search_all(
    session: Session, query: str, limit: int = 50, project_ids: Iterable[int] | None = None
) -> list[SearchHit]:
    """Cross-project search: every project's ranked hits merged by score.

    Each hit carries ``project_id`` so the UI can say which project it came from.
    """
    hits: list[SearchHit] = []
    for pid in _project_ids(session, project_ids):
        hits.extend(search_index.search(session, pid, query, limit))
    hits.sort(key=lambda h: (-h.score, h.project_id or 0, h.experiment_id, h.field, h.snippet))
    return hits[:limit]


_PARTICLES = tuple(
    sorted(
        (
            "에서는",
            "에서",
            "으로",
            "로는",
            "에는",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "의",
            "에",
            "로",
            "와",
            "과",
            "도",
            "만",
        ),
        key=len,
        reverse=True,
    )
)
_STOPWORDS = frozenset(
    {
        "실험",
        "결과",
        "관련",
        "관련된",
        "어떤",
        "무엇",
        "뭐",
        "있나",
        "있는",
        "했나",
        "했던",
        "대한",
        "어떻게",
        "왜",
        "언제",
        "보여줘",
        "알려줘",
        "찾아줘",
        "사용한",
        "쓴",
        "the",
        "what",
        "which",
        "of",
        "and",
        "in",
        "with",
        "for",
        "a",
        "an",
        "is",
        "was",
    }
)
_TOKEN = re.compile(r"[\w#.+\-/]+", re.UNICODE)


def recall_terms(query: str) -> list[str]:
    """Keyword terms of a free-text query (Korean particles and stopwords removed)."""
    terms: list[str] = []
    for raw in _TOKEN.findall(query.lower()):
        token = raw.strip(".-/")
        for p in _PARTICLES:
            if len(token) > len(p) + 1 and token.endswith(p):
                token = token[: -len(p)]
                break
        if token and token not in _STOPWORDS and token not in terms:
            terms.append(token)
    return terms


_FACET_ORDER: tuple[Facet, ...] = ("strain", "sample", "analyte", "condition")


def _facet_entries(vocab: ExperimentVocab, facet: Facet) -> Iterable[str]:
    if facet == "strain":
        return vocab.strains
    if facet == "sample":
        return vocab.samples
    if facet == "analyte":
        return vocab.analytes
    return vocab.conditions


def _facet_hit(exp: ExperimentOut, vocab: ExperimentVocab, facet: Facet, entry: str) -> SearchHit:
    if facet == "analyte":
        src = SourceRef(
            ref_type="eln.Dataset",
            ref_id=vocab.analytes[entry],
            field="content.analyte",
            experiment_id=exp.id,
        )
        return SearchHit(
            experiment_id=exp.id,
            code=exp.code,
            field="dataset",
            snippet=f"분석물: {entry}",
            score=2.0,
            source=src,
        )
    if facet == "condition":
        key = vocab.conditions[entry]
        return SearchHit(
            experiment_id=exp.id,
            code=exp.code,
            field="condition_block",
            snippet=entry,
            score=2.0,
            source=condition_source(exp, key),
        )
    path = (vocab.samples if facet == "sample" else vocab.strains)[entry]
    if path.startswith("dataset:"):
        ds_id = int(path.split(":", 1)[1].split(".", 1)[0])
        src = SourceRef(
            ref_type="eln.Dataset", ref_id=ds_id, field="content.sample_id", experiment_id=exp.id
        )
        fld = "dataset"
    else:
        src = SourceRef(ref_type="eln.Experiment", ref_id=exp.id, field=path, experiment_id=exp.id)
        fld = "condition_block"
    return SearchHit(
        experiment_id=exp.id,
        code=exp.code,
        field=fld,
        snippet=f"{'균주' if facet == 'strain' else '시료'}: {entry}",
        score=2.0,
        source=src,
    )


def recall(session: Session, project_id: int, query: str, limit: int = 10) -> RecallBundle:
    """Bundle experiments, protocols and stored results related to keywords.

    Terms are classified into strain / sample / analyte / condition facets against
    the project's own vocabulary; anything else is a free-text keyword.
    """
    terms = recall_terms(query)
    exps = eln.list_experiments_full(session, project_id)
    vocabs = {e.id: experiment_vocab(session, e) for e in exps}
    by_id = {e.id: e for e in exps}
    matched: list[MatchedTerm] = []
    reasons: dict[int, list[SearchHit]] = {e.id: [] for e in exps}
    scores: dict[int, float] = dict.fromkeys(by_id, 0.0)
    analyte_matches: set[str] = set()
    for term in terms:
        facet: Facet = "keyword"
        entries: list[str] = []
        for candidate in _FACET_ORDER:
            for e in exps:
                for entry in _facet_entries(vocabs[e.id], candidate):
                    if term in entry.lower():
                        if entry not in entries:
                            entries.append(entry)
                        reasons[e.id].append(_facet_hit(e, vocabs[e.id], candidate, entry))
                        scores[e.id] += 2.0
            if entries:
                facet = candidate
                break
        if facet == "analyte":
            analyte_matches.update(x.lower() for x in entries)
        for hit in search_index.search(session, project_id, term, limit=200):
            if hit.experiment_id in scores:
                scores[hit.experiment_id] += 1.0 + 0.01 * hit.score
                reasons[hit.experiment_id].append(hit)
        matched.append(MatchedTerm(term=term, facet=facet, matches=sorted(entries)))

    ranked = sorted(
        (i for i in scores if scores[i] > 0),
        key=lambda i: (-scores[i], by_id[i].performed_on, i),
    )[:limit]
    experiments: list[RecallExperiment] = []
    for i in ranked:
        seen: set[tuple[str, int, str, str]] = set()
        unique: list[SearchHit] = []
        for h in sorted(reasons[i], key=lambda h: -h.score):
            src = h.source
            key = (
                (src.ref_type, src.ref_id, src.field, h.snippet) if src else ("", 0, "", h.snippet)
            )
            if key not in seen:
                seen.add(key)
                unique.append(h)
        experiments.append(
            RecallExperiment(
                experiment=_summary(by_id[i]), score=round(scores[i], 4), reasons=unique[:6]
            )
        )

    groups: dict[str, list[ExperimentOut]] = {}
    for i in ranked:
        groups.setdefault(protocol_id(conditions(by_id[i])), []).append(by_id[i])
    first: dict[str, Any] | None = None
    protocols: list[ProtocolGroup] = []
    for pid, members in groups.items():
        cond = conditions(members[0])
        first = first if first is not None else cond
        protocols.append(
            ProtocolGroup(
                protocol_id=pid,
                experiment_ids=[m.id for m in members],
                codes=[m.code for m in members],
                conditions=cond,
                differs_from_first=sorted(
                    k for k in set(cond) | set(first) if cond.get(k) != first.get(k)
                ),
            )
        )

    results: list[ResultFact] = []
    for i in ranked:
        for r in ports.results(session, i):
            if analyte_matches:
                if r.analyte is None or r.analyte.lower() in analyte_matches:
                    results.append(r)
            elif r.analyte is None:
                results.append(r)
    for x in experiments:
        for h in x.reasons:
            h.project_id = project_id
    return RecallBundle(
        query=query,
        terms=matched,
        experiments=experiments,
        protocols=protocols,
        results=results,
        project_ids=[project_id],
    )


def recall_all(
    session: Session, query: str, limit: int = 10, project_ids: Iterable[int] | None = None
) -> RecallBundle:
    """Cross-project recall: :func:`recall` per project, merged.

    Experiments are ranked by score across projects (``experiment.project_id`` names
    the project); facets are classified against each project's own vocabulary and a
    term keeps the first non-keyword facet it matched anywhere.
    """
    pids = _project_ids(session, project_ids)
    bundles = [recall(session, pid, query, limit) for pid in pids]
    terms: dict[str, MatchedTerm] = {}
    for b in bundles:
        for t in b.terms:
            cur = terms.get(t.term)
            if cur is None:
                terms[t.term] = t.model_copy(deep=True)
                continue
            if cur.facet == "keyword" and t.facet != "keyword":
                cur.facet = t.facet
            cur.matches = sorted(set(cur.matches) | set(t.matches))
    ranked = sorted(
        (x for b in bundles for x in b.experiments),
        key=lambda x: (-x.score, x.experiment.performed_on, x.experiment.id),
    )[:limit]
    kept = {x.experiment.id for x in ranked}
    for x in ranked:
        for h in x.reasons:
            h.project_id = x.experiment.project_id
    return RecallBundle(
        query=query,
        terms=list(terms.values()),
        experiments=ranked,
        protocols=[
            p for b in bundles for p in b.protocols if any(i in kept for i in p.experiment_ids)
        ],
        results=[r for b in bundles for r in b.results if r.source.experiment_id in kept],
        project_ids=pids,
    )


def failure_archive(session: Session, project_ids: Iterable[int] | None = None) -> FailureArchive:
    """Failures (stored critical QC), their type and repeat patterns across projects."""
    return failure_archive_mod.archive(session, _project_ids(session, project_ids))


_FIELD_LABELS = {
    "title": "제목",
    "raw_note": "원본 메모",
    "condition_block": "조건",
    "digest": "정리본",
    "critique": "비판 요약",
    "knowledge_note": "지식 노트",
    "dataset": "데이터셋",
}


def _fmt_number(value: float) -> str:
    """Four significant digits — enough to quote a stored value without false precision."""
    return f"{value:.4g}"


def evidence_fragments(bundle: RecallBundle, limit: int) -> list[EvidenceFragment]:
    """Turn a recall bundle into keyed evidence fragments.

    Candidates are taken round-robin across the ranked experiments, alternating stored
    results and text reasons inside each experiment, so a small ``limit`` still covers
    several experiments and both kinds of evidence.
    """
    codes = {x.experiment.id: x.experiment.code for x in bundle.experiments}
    per_exp: dict[int, list[tuple[str, SourceRef]]] = {}
    for x in bundle.experiments:
        code = x.experiment.code
        results = [
            (f"{code} {r.label}: {_fmt_number(r.value)}{f' {r.unit}' if r.unit else ''}", r.source)
            for r in bundle.results
            if r.source.experiment_id == x.experiment.id and r.value is not None
        ]
        texts = [
            (f"{code} {_FIELD_LABELS[h.field]}: {h.snippet}", h.source)
            for h in x.reasons
            if h.source is not None
        ]
        merged: list[tuple[str, SourceRef]] = []
        for k in range(max(len(results), len(texts))):
            merged += results[k : k + 1] + texts[k : k + 1]
        per_exp[x.experiment.id] = merged
    fragments: list[EvidenceFragment] = []
    depth = 0
    while len(fragments) < limit and any(depth < len(v) for v in per_exp.values()):
        for exp_id, items in per_exp.items():
            if depth < len(items) and len(fragments) < limit:
                body, source = items[depth]
                fragments.append(
                    EvidenceFragment(
                        key=f"F{len(fragments) + 1}",
                        experiment_id=exp_id,
                        code=codes[exp_id],
                        text=body,
                        source=source,
                    )
                )
        depth += 1
    return fragments


ASK_SYSTEM = (
    "You answer questions about a laboratory's research memory. Use ONLY the numbered "
    "evidence fragments provided. Write in Korean, 2–4 sentences, cite fragments as [F#], "
    "and never state a number that does not appear in the fragments. List every fragment "
    "key you relied on in fragment_keys."
)


def _rules_answer(question: str, fragments: list[EvidenceFragment]) -> MemoryAnswerDraft:
    if not fragments:
        return MemoryAnswerDraft(
            answer="연구 기억에서 이 질문과 관련된 기록을 찾지 못했습니다.", fragment_keys=[]
        )
    lines = [f"[{f.key}] {f.text}" for f in fragments]
    head = f"연구 기억에서 관련 근거 {len(fragments)}건을 찾았습니다 (규칙 모드: 근거 조각만 제시)."
    return MemoryAnswerDraft(
        answer=head + "\n" + "\n".join(lines), fragment_keys=[f.key for f in fragments]
    )


def ask(
    session: Session,
    project_id: int,
    request: MemoryAskRequest,
    *,
    gateway: LLMGateway | None = None,
) -> MemoryAnswer:
    """Question answering over research memory with evidence fragments.

    Rules mode (default) returns the fragments themselves. Claude mode summarises
    them; a summary citing unknown fragments or ungrounded numbers is replaced by the
    rules answer and ``fallback_reason`` explains why. Read-only: nothing is stored.
    """
    gw = gateway or get_gateway()
    bundle = recall(session, project_id, request.question, limit=request.limit)
    fragments = evidence_fragments(bundle, request.limit)
    engine = "rules"
    fallback: str | None = None
    draft: MemoryAnswerDraft | None = None
    if gw.mode == "claude" and fragments:
        prompt = f"질문: {request.question}\n\n근거 조각:\n" + "\n".join(
            f"[{f.key}] {f.text}" for f in fragments
        )
        draft = gw.generate(system=ASK_SYSTEM, prompt=prompt, schema=MemoryAnswerDraft)
        known = {f.key for f in fragments}
        if draft is None:
            fallback = "claude_unavailable"
        elif not draft.fragment_keys or set(draft.fragment_keys) - known:
            fallback = "unknown_fragment_keys: " + ", ".join(
                sorted(set(draft.fragment_keys) - known) or ["(none cited)"]
            )
            draft = None
        elif bad := ungrounded_numbers(
            draft.answer, [f.text for f in fragments] + [request.question]
        ):
            fallback = "ungrounded_numbers: " + ", ".join(bad[:5])
            draft = None
        else:
            engine = "claude"
    if draft is None:
        draft = _rules_answer(request.question, fragments)
    return MemoryAnswer(
        question=request.question,
        answer=draft.answer,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        fallback_reason=fallback,
        fragment_keys=draft.fragment_keys,
        fragments=fragments,
    )


# ---------------------------------------------------------------- digests


def digest_fingerprint(session: Session, exp: ExperimentOut) -> str:
    """sha256 over the inputs a digest is derived from (note, conditions, datasets, parent)."""
    parent = (
        eln.get_experiment(session, exp.parent_experiment_id) if exp.parent_experiment_id else None
    )
    payload = {
        "code": exp.code,
        "title": exp.title,
        "raw_note": exp.raw_note,
        "conditions": conditions(exp),
        "datasets": sorted(d.sha256 for d in eln.list_datasets(session, exp.id)),
        "parent_conditions": conditions(parent) if parent else None,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rules_digest(exp: ExperimentOut, parent: ExperimentOut | None) -> DigestDraft:
    """Deterministic digest: condition summary + bullet lines quoted from the note."""
    cond = conditions(exp)
    parts = [
        f"{CONDITION_FIELD_LABELS[k]} {display(cond[k])}"
        for k in ("extraction_solvent", "extraction_time_min", "ph", "cleanup_sorbent", "column")
        if k in cond
    ]
    summary = f"{exp.code} {exp.title}. 주요 조건: " + ", ".join(parts) + "."
    if parent is not None:
        changes = condition_changes(parent, exp)
        if changes:
            changed = "; ".join(
                f"{c.label} {display(c.value_a)} → {display(c.value_b)}" for c in changes
            )
            summary += f" {parent.code} 대비 변경: {changed}."
    bullets = [
        line.strip().lstrip("-•").strip()
        for line in exp.raw_note.splitlines()
        if line.strip().startswith(("-", "•"))
    ]
    return DigestDraft(summary=summary, key_points=bullets[:8])


def _digest_sources(exp: ExperimentOut, parent: ExperimentOut | None) -> list[str]:
    texts = [exp.code, exp.title, exp.raw_note, exp.performed_on.isoformat()]
    for e in (exp, parent):
        if e is None:
            continue
        texts.append(e.code)
        for v in conditions(e).values():
            texts += [str(v), display(v)]
    return texts


DIGEST_SYSTEM = (
    "You summarise laboratory notebook entries for an analytical chemistry team. "
    "Write in Korean. Only restate what the note and condition block say; never invent "
    "numbers, results or conclusions that are not present in the input."
)


def _digest_out(row: ExperimentDigest, current_fingerprint: str | None) -> DigestOut:
    out = DigestOut.model_validate(row)
    stale = (
        row.input_fingerprint is not None
        and current_fingerprint is not None
        and row.input_fingerprint != current_fingerprint
    )
    return out.model_copy(update={"stale": stale})


def create_digest(
    session: Session,
    experiment_id: int,
    *,
    gateway: LLMGateway | None = None,
    actor: Actor | None = None,
) -> DigestOut:
    """Create and store a digest (Claude when available and grounded, otherwise rules)."""
    gw = gateway or get_gateway()
    exp = eln.get_experiment(session, experiment_id)
    parent = (
        eln.get_experiment(session, exp.parent_experiment_id) if exp.parent_experiment_id else None
    )
    draft: DigestDraft | None = None
    engine = "rules"
    fallback: str | None = None
    if gw.mode == "claude":
        prompt = (
            f"Experiment {exp.code}: {exp.title}\n\nCondition block (JSON):\n"
            f"{exp.condition_block.model_dump_json(exclude_none=True)}\n\nRaw note:\n{exp.raw_note}"
        )
        draft = gw.generate(system=DIGEST_SYSTEM, prompt=prompt, schema=DigestDraft)
        if draft is None:
            fallback = "claude_unavailable"
        else:
            body = draft.summary + "\n" + "\n".join(draft.key_points)
            bad = ungrounded_numbers(body, _digest_sources(exp, parent))
            if bad:
                fallback = "ungrounded_numbers: " + ", ".join(bad[:5])
                draft = None
            else:
                engine = "claude"
    if draft is None:
        draft = rules_digest(exp, parent)
    fingerprint = digest_fingerprint(session, exp)
    row = ExperimentDigest(
        experiment_id=experiment_id,
        engine=engine,
        model=gw.model_name if engine == "claude" else None,
        summary=draft.summary,
        key_points=draft.key_points,
        fallback_reason=fallback,
        input_fingerprint=fingerprint,
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
        payload={"experiment_id": experiment_id, "engine": engine, "fallback": fallback},
    )
    return _digest_out(row, fingerprint)


def list_digests(session: Session, experiment_id: int) -> list[DigestOut]:
    """All digests of an experiment, newest first, each with a ``stale`` flag."""
    exp = eln.get_experiment(session, experiment_id)
    current = digest_fingerprint(session, exp)
    rows = session.scalars(
        select(ExperimentDigest)
        .where(ExperimentDigest.experiment_id == experiment_id)
        .order_by(ExperimentDigest.id.desc())
    )
    return [_digest_out(r, current) for r in rows]


def get_digest(session: Session, digest_id: int) -> DigestOut:
    """One digest by id (with ``stale`` flag)."""
    row = session.get(ExperimentDigest, digest_id)
    if row is None:
        raise NotFoundError(f"Digest {digest_id} not found")
    exp = eln.get_experiment(session, row.experiment_id)
    return _digest_out(row, digest_fingerprint(session, exp))


# -------------------------------------------------------- knowledge notes


def create_knowledge_note(
    session: Session, project_id: int, data: KnowledgeNoteCreate, *, actor: Actor = "user"
) -> KnowledgeNoteOut:
    """Store an immutable researcher knowledge note linked to existing experiments."""
    eln.get_project(session, project_id)
    linked = list(dict.fromkeys(data.linked_experiment_ids))
    for exp_id in linked:
        try:
            exp = eln.get_experiment(session, exp_id)
        except NotFoundError as exc:
            raise ValidationFailedError(f"linked experiment {exp_id} does not exist") from exc
        if exp.project_id != project_id:
            raise ValidationFailedError(f"linked experiment {exp_id} belongs to another project")
    note = KnowledgeNote(
        project_id=project_id,
        statement=data.statement,
        linked_experiment_ids=linked,
        author=data.author,
    )
    session.add(note)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="memory.KnowledgeNote",
        entity_id=note.id,
        project_id=project_id,
        payload={"linked_experiment_ids": linked},
    )
    return KnowledgeNoteOut.model_validate(note)


def list_knowledge_notes(session: Session, project_id: int) -> KnowledgeNoteList:
    """Knowledge notes of a project, newest first."""
    eln.get_project(session, project_id)
    rows = list(
        session.scalars(
            select(KnowledgeNote)
            .where(KnowledgeNote.project_id == project_id)
            .order_by(KnowledgeNote.id.desc())
        )
    )
    return KnowledgeNoteList(
        project_id=project_id,
        total=len(rows),
        items=[KnowledgeNoteOut.model_validate(r) for r in rows],
    )
