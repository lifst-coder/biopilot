"""Failure archive: which experiments failed, after what change, and which failures repeat.

A *failure* is an experiment whose stored QC (read through the fact port, never
recomputed) carries a ``critical`` flag. Everything here is deterministic bookkeeping
over the record graph — Memory does not judge causes (that is Partner) and does not
compute analytical numbers (recovery values are copied from stored results).

Failure type
    Derived from the condition changes versus the parent experiment:
    ``initial`` (no parent), ``no_change`` (identical condition block — a
    reproduction failure), ``change:<key>`` (exactly one key changed) or
    ``multi_change`` (several keys changed at once). Every failure has one type.

Repeat pattern
    Failures are linked when (a) a child of a failed experiment fails again
    (``retry``) or (b) a later failure keeps a condition value that an earlier failure
    introduced *and* misses at least one of the same analytes (``same_condition``) —
    only when the later one re-applies the change to the same parent experiment or
    descends from the earlier failure (a value that later became the standard
    protocol is not a repeat).
    Connected groups of two or more failures are patterns. The *resolution* of a
    pattern is the earliest child of a member that is not itself a failure, has a
    stored recovery and no critical flag.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.eln import service as eln
from app.eln.schemas import ExperimentOut, ExperimentSummary
from app.memory import ports
from app.memory.conditions import condition_changes, conditions, label
from app.memory.schemas import (
    ConditionChange,
    FailureArchive,
    FailurePattern,
    FailurePatternLink,
    FailureRecord,
    FailureType,
    QCFact,
    ResultFact,
)

RECOVERY_METRIC = "recovery_mean_pct"

_TYPE_LABELS = {
    "initial": "초기 조건에서 실패",
    "no_change": "조건 변경 없이 실패 (재현 실패)",
    "multi_change": "여러 조건을 한 번에 바꾼 뒤 실패",
}


@dataclass
class _Exp:
    """One experiment with the stored facts the archive needs."""

    exp: ExperimentOut
    project_name: str
    flags: list[QCFact]
    results: list[ResultFact]
    parent: ExperimentOut | None = None
    children: list[int] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(f.severity == "critical" for f in self.flags)

    @property
    def analyzed(self) -> bool:
        return bool(self.results) or bool(self.flags)

    @property
    def recovery(self) -> ResultFact | None:
        return next((r for r in self.results if r.metric == RECOVERY_METRIC), None)

    @property
    def failed_analytes(self) -> list[str]:
        return sorted({f.analyte for f in self.flags if f.severity == "critical" and f.analyte})

    @property
    def changes(self) -> list[ConditionChange]:
        return condition_changes(self.parent, self.exp) if self.parent else []


def _summary(exp: ExperimentOut) -> ExperimentSummary:
    return ExperimentSummary.model_validate(exp.model_dump())


def _order(x: _Exp) -> tuple[object, int]:
    return (x.exp.performed_on, x.exp.id)


def failure_type(item: _Exp) -> tuple[str, str]:
    """``(type_id, Korean label)`` of a failure from its changes versus the parent."""
    if item.parent is None:
        return "initial", _TYPE_LABELS["initial"]
    changes = item.changes
    if not changes:
        return "no_change", _TYPE_LABELS["no_change"]
    if len(changes) == 1:
        key = changes[0].key
        return f"change:{key}", f"{label(key)} 변경 후 실패"
    return "multi_change", _TYPE_LABELS["multi_change"]


def load(session: Session, project_ids: Iterable[int] | None = None) -> dict[int, _Exp]:
    """Experiments of the given projects (default: all) with QC flags and results."""
    projects = eln.list_projects(session)
    wanted = set(project_ids) if project_ids is not None else {p.id for p in projects}
    items: dict[int, _Exp] = {}
    for p in projects:
        if p.id not in wanted:
            continue
        exps = eln.list_experiments_full(session, p.id)
        ids = [e.id for e in exps]
        results, flags = ports.facts_many(session, ids)  # batched: not one read per experiment
        for e in exps:
            items[e.id] = _Exp(
                exp=e, project_name=p.name, flags=flags[e.id] or [], results=results[e.id]
            )
    for item in items.values():
        pid = item.exp.parent_experiment_id
        if pid is not None and pid in items:
            item.parent = items[pid].exp
            items[pid].children.append(item.exp.id)
    return items


def _record(item: _Exp, items: dict[int, _Exp]) -> FailureRecord:
    type_id, type_label = failure_type(item)
    parent = items.get(item.exp.parent_experiment_id or -1)
    return FailureRecord(
        experiment=_summary(item.exp),
        project_name=item.project_name,
        parent=_summary(parent.exp) if parent else None,
        parent_failed=bool(parent and parent.failed),
        type_id=type_id,
        type_label=type_label,
        failed_checks=sorted({f.code for f in item.flags if f.severity == "critical"}),
        failed_analytes=item.failed_analytes,
        changes=item.changes,
        recovery=item.recovery,
        sources=[f.source for f in item.flags if f.severity == "critical"],
    )


def _ancestors(item: _Exp, items: dict[int, _Exp]) -> set[int]:
    """Ids on ``item``'s parent chain (stops at a cycle or an experiment outside ``items``)."""
    seen: set[int] = set()
    cur = item.exp.parent_experiment_id
    while cur is not None and cur not in seen and cur in items:
        seen.add(cur)
        cur = items[cur].exp.parent_experiment_id
    return seen


def _same_base(earlier: _Exp, later: _Exp, later_ancestors: set[int]) -> bool:
    """``later`` re-applies ``earlier``'s change to the same parent, or inherits it."""
    same_parent = (
        earlier.exp.parent_experiment_id is not None
        and later.exp.parent_experiment_id == earlier.exp.parent_experiment_id
    )
    return same_parent or earlier.exp.id in later_ancestors


def _links(failures: list[_Exp], items: dict[int, _Exp]) -> list[FailurePatternLink]:
    """Retry and same-condition links between failures (earlier → later)."""
    links: list[FailurePatternLink] = []
    by_id = {f.exp.id: f for f in failures}
    for later in failures:
        earlier = by_id.get(later.exp.parent_experiment_id or -1)
        if earlier is not None:
            links.append(
                FailurePatternLink(
                    kind="retry",
                    from_experiment_id=earlier.exp.id,
                    to_experiment_id=later.exp.id,
                    shared_analytes=sorted(
                        set(later.failed_analytes) & set(earlier.failed_analytes)
                    ),
                )
            )
    # Each failure's parent chain is walked once, not once per (earlier, later) pair.
    ancestors = {f.exp.id: _ancestors(f, items) for f in failures}
    for i, earlier in enumerate(failures):
        introduced = [c for c in earlier.changes if c.change != "removed"]
        if not introduced:
            continue
        for later in failures[i + 1 :]:
            if later.exp.parent_experiment_id == earlier.exp.id:
                continue  # already a retry link
            if not _same_base(earlier, later, ancestors[later.exp.id]):
                continue
            shared = sorted(set(earlier.failed_analytes) & set(later.failed_analytes))
            if not shared:
                continue
            cond = conditions(later.exp)
            for c in introduced:
                if c.key in cond and cond[c.key] == c.value_b:
                    links.append(
                        FailurePatternLink(
                            kind="same_condition",
                            from_experiment_id=earlier.exp.id,
                            to_experiment_id=later.exp.id,
                            key=c.key,
                            label=label(c.key),
                            value=c.value_b,
                            shared_analytes=shared,
                        )
                    )
                    break
    return links


def _groups(failures: list[_Exp], links: list[FailurePatternLink]) -> list[list[_Exp]]:
    parent: dict[int, int] = {f.exp.id: f.exp.id for f in failures}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in links:
        a, b = find(link.from_experiment_id), find(link.to_experiment_id)
        if a != b:
            parent[max(a, b)] = min(a, b)
    groups: dict[int, list[_Exp]] = {}
    for f in failures:
        groups.setdefault(find(f.exp.id), []).append(f)
    return [sorted(g, key=_order) for g in groups.values() if len(g) >= 2]


def _resolution(members: list[_Exp], items: dict[int, _Exp]) -> _Exp | None:
    ids = {m.exp.id for m in members}
    candidates = [
        items[c]
        for m in members
        for c in m.children
        if c not in ids and not items[c].failed and items[c].recovery is not None
    ]
    return min(candidates, key=_order) if candidates else None


def _pattern(
    members: list[_Exp], links: list[FailurePatternLink], items: dict[int, _Exp]
) -> FailurePattern:
    ids = {m.exp.id for m in members}
    counts: dict[str, int] = {}
    for m in members:
        for a in m.failed_analytes:
            counts[a] = counts.get(a, 0) + 1
    res = _resolution(members, items)
    return FailurePattern(
        id="pattern:" + "-".join(str(m.exp.id) for m in members),
        experiment_ids=[m.exp.id for m in members],
        codes=[m.exp.code for m in members],
        project_ids=sorted({m.exp.project_id for m in members}),
        shared_analytes=sorted(a for a, n in counts.items() if n >= 2),
        links=[x for x in links if x.from_experiment_id in ids and x.to_experiment_id in ids],
        resolution=_summary(res.exp) if res else None,
        resolution_qc=("warning" if any(f.severity == "warning" for f in res.flags) else "pass")
        if res
        else None,
        resolution_changes=res.changes if res else [],
        resolution_recovery=res.recovery if res else None,
    )


def archive(session: Session, project_ids: Iterable[int] | None = None) -> FailureArchive:
    """Failure archive over the given projects (default: every project)."""
    items = load(session, project_ids)
    failures = sorted((x for x in items.values() if x.failed), key=_order)
    records = [_record(f, items) for f in failures]
    types: dict[str, FailureType] = {}
    for r in records:
        t = types.setdefault(
            r.type_id, FailureType(id=r.type_id, label=r.type_label, count=0, experiment_ids=[])
        )
        t.count += 1
        t.experiment_ids.append(r.experiment.id)
    links = _links(failures, items)
    patterns = [_pattern(g, links, items) for g in _groups(failures, links)]
    patterns.sort(key=lambda p: (-len(p.experiment_ids), p.experiment_ids[0]))
    return FailureArchive(
        project_ids=sorted({x.exp.project_id for x in items.values()}),
        experiment_count=len(items),
        analyzed_count=sum(1 for x in items.values() if x.analyzed),
        failure_count=len(records),
        types=sorted(types.values(), key=lambda t: (-t.count, t.label)),
        patterns=patterns,
        failures=list(reversed(records)),
    )
