"""Condition-block helpers: changes with provenance, condition vectors, similarity.

All functions are pure and deterministic. The similarity score is a retrieval
ranking over stored condition values, not an analytical result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from app.eln.schemas import CONDITION_FIELD_LABELS, ExperimentOut
from app.memory.schemas import ConditionChange, ProposalFact, SourceRef

#: Condition keys treated as "sample" (시료) facets in recall and the knowledge graph.
SAMPLE_KEYS: tuple[str, ...] = ("matrix", "sample", "sample_type", "시료")
#: Condition keys treated as "strain" (균주) facets.
STRAIN_KEYS: tuple[str, ...] = ("strain", "organism", "cell_line", "균주")

EXPERIMENT_REF = "eln.Experiment"


def display(value: Any) -> str:
    """Compact rendering of condition values (``10.0`` → ``10``)."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def conditions(exp: ExperimentOut) -> dict[str, Any]:
    """Condition block as a plain dict without unset keys."""
    return exp.condition_block.model_dump(exclude_none=True)


def label(key: str) -> str:
    """Korean label of a condition key (falls back to the key)."""
    return CONDITION_FIELD_LABELS.get(key, key)


def condition_source(exp: ExperimentOut, key: str) -> SourceRef:
    """Source reference of one condition value."""
    return SourceRef(
        ref_type=EXPERIMENT_REF, ref_id=exp.id, field=f"condition_block.{key}", experiment_id=exp.id
    )


def condition_changes(a: ExperimentOut, b: ExperimentOut) -> list[ConditionChange]:
    """Key-by-key comparison of two condition blocks (b relative to a) with sources."""
    ca, cb = conditions(a), conditions(b)
    changes: list[ConditionChange] = []
    for key in sorted(set(ca) | set(cb)):
        sources = [condition_source(e, key) for e, c in ((a, ca), (b, cb)) if key in c]
        if key not in ca:
            kind = "added"
        elif key not in cb:
            kind = "removed"
        elif ca[key] != cb[key]:
            kind = "changed"
        else:
            continue
        changes.append(
            ConditionChange(
                key=key,
                label=label(key),
                change=kind,
                value_a=ca.get(key),
                value_b=cb.get(key),
                sources=sources,
            )
        )
    return changes


def protocol_id(cond: dict[str, Any]) -> str:
    """Short, stable fingerprint of a condition block (identifies a protocol variant)."""
    raw = json.dumps(cond, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def numeric_ranges(experiments: Iterable[ExperimentOut]) -> dict[str, float]:
    """Max − min of every numeric condition key across the given experiments."""
    lo: dict[str, float] = {}
    hi: dict[str, float] = {}
    for e in experiments:
        for k, v in conditions(e).items():
            if _is_number(v):
                lo[k] = min(lo.get(k, v), v)
                hi[k] = max(hi.get(k, v), v)
    return {k: hi[k] - lo[k] for k in lo}


def _norm_text(v: Any) -> str:
    return " ".join(str(v).split()).casefold()


def key_similarity(a: Any, b: Any, value_range: float | None) -> float:
    """Per-key similarity in [0, 1]: numeric → 1 − |Δ|/range, categorical → equality."""
    if _is_number(a) and _is_number(b):
        if a == b:
            return 1.0
        if not value_range:
            return 0.0
        return max(0.0, 1.0 - abs(float(a) - float(b)) / value_range)
    return 1.0 if _norm_text(a) == _norm_text(b) else 0.0


def similarity(
    ca: dict[str, Any], cb: dict[str, Any], ranges: dict[str, float]
) -> tuple[float, list[str]]:
    """Mean per-key similarity over the union of keys (missing key → 0).

    Returns ``(score, shared_keys)`` where ``shared_keys`` have identical values.
    """
    keys = sorted(set(ca) | set(cb))
    if not keys:
        return 1.0, []
    total = 0.0
    shared: list[str] = []
    for k in keys:
        if k in ca and k in cb:
            s = key_similarity(ca[k], cb[k], ranges.get(k))
            total += s
            if s == 1.0:
                shared.append(k)
    return round(total / len(keys), 4), shared


def similar_pairs(
    experiments: Sequence[ExperimentOut], threshold: float
) -> list[tuple[int, int, float]]:
    """All unordered pairs ``(id_lo, id_hi, score)`` with similarity ≥ ``threshold``."""
    ranges = numeric_ranges(experiments)
    conds = {e.id: conditions(e) for e in experiments}
    ids = sorted(conds)
    pairs: list[tuple[int, int, float]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            score, _ = similarity(conds[a], conds[b], ranges)
            if score >= threshold:
                pairs.append((a, b, score))
    return pairs


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _value_matches(actual: Any, proposed: Any) -> bool:
    if _is_number(actual) and _is_number(proposed):
        return float(actual) == float(proposed)
    if _is_number(actual) and isinstance(proposed, str):
        try:
            return float(actual) == float(proposed)
        except ValueError:
            return False
    return _norm_text(actual) == _norm_text(proposed)


def _after_proposal(e: ExperimentOut, p: ProposalFact) -> bool:
    """``e`` was performed after the proposal was made (or decided).

    The proposal's day is its decision day when given (a back-filled lab history is
    written long after the fact), else the day it was created. A same-day experiment
    counts only when it was recorded after the proposal.
    """
    since = p.decided_on or p.created_at.date()
    if e.performed_on != since:
        return e.performed_on > since
    return _naive(e.created_at) > _naive(p.created_at)


def _applies(cond: dict[str, Any], changes: dict[str, Any]) -> bool:
    return all(
        (v is None and k not in cond) or (k in cond and _value_matches(cond[k], v))
        for k, v in changes.items()
    )


def proposal_tests(
    experiments: Sequence[ExperimentOut], proposals: Sequence[ProposalFact]
) -> list[tuple[int, int]]:
    """``(proposal_id, experiment_id)`` for experiments that carried a proposal out
    (MEM-1 ``tests_proposal``).

    An experiment tests a proposal when it was performed after the proposal (or its
    decision), its condition block applies every implementing change, and it *made*
    at least one of those changes relative to its own parent — inheriting a value
    from the parent is not testing it. The experiment may sit anywhere in the
    project's lineage: a single-variable change of #024 is usually run from the
    baseline (#018), and an accepted change may be adopted later in a new SOP branch.
    Rejected proposals are never "tested"; ``changes`` are Partner's implementing
    changes (design descriptors and values still to be chosen already removed).
    """
    by_id = {e.id: e for e in experiments}
    links: list[tuple[int, int]] = []
    for p in proposals:
        if not p.changes or p.status == "rejected":
            continue
        for e in experiments:
            parent = by_id.get(e.parent_experiment_id) if e.parent_experiment_id else None
            if parent is None or e.id == p.experiment_id or not _after_proposal(e, p):
                continue
            cond = conditions(e)
            if not _applies(cond, p.changes):
                continue
            before = conditions(parent)
            if any(not _applies(before, {k: v}) for k, v in p.changes.items()):
                links.append((p.id, e.id))
    return links
