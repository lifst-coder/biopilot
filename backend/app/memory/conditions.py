"""Condition-block helpers: changes with provenance, condition vectors, similarity.

All functions are pure and deterministic. The similarity score is a retrieval
ranking over stored condition values, not an analytical result.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

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


def changed_keys(a: ExperimentOut, b: ExperimentOut) -> list[str]:
    """Keys of :func:`condition_changes` (same keys, same order) without building the
    change records — for callers that only list which keys changed."""
    return changed_condition_keys(conditions(a), conditions(b))


def changed_condition_keys(
    ca: dict[str, Any],
    cb: dict[str, Any],
    sorted_a: list[str] | None = None,
    sorted_b: list[str] | None = None,
) -> list[str]:
    """:func:`changed_keys` of two condition dicts (from :func:`conditions`).

    ``sorted_a`` / ``sorted_b`` (``sorted(ca)`` / ``sorted(cb)``, precomputed by callers
    comparing many pairs) skip building and sorting the key union when both blocks have
    the same keys.
    """
    if sorted_a is not None and sorted_a == sorted_b:
        return [k for k in sorted_a if ca[k] != cb[k]]
    return [k for k in sorted(set(ca) | set(cb)) if k not in ca or k not in cb or ca[k] != cb[k]]


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


#: Safety margin of the candidate pruning in :func:`similar_pairs`. A pair is skipped only
#: when its score is *provably* below ``threshold - PRUNE_MARGIN`` (far below any rounding
#: of the 4-decimal score), so pruning never drops a qualifying pair.
PRUNE_MARGIN = 1e-3


def similar_pairs_bruteforce(
    experiments: Sequence[ExperimentOut], threshold: float
) -> list[tuple[int, int, float]]:
    """Reference implementation of :func:`similar_pairs`: :func:`similarity` on every pair.

    O(n²); kept as the specification the pruned version is tested against.
    """
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


_Prepared = dict[str, tuple[bool, Any, str]]  # key → (is_number, raw value, normalised text)


def _prepare(cond: dict[str, Any]) -> _Prepared:
    return {k: (_is_number(v), v, _norm_text(v)) for k, v in cond.items()}


def _prepared_similarity(a: _Prepared, b: _Prepared, ranges: dict[str, float]) -> float:
    """Score of :func:`similarity` from values normalised once per experiment.

    Same branches, same key order and the same float operations as
    :func:`similarity` / :func:`key_similarity`, so the result is bit-identical.
    """
    keys = sorted(a.keys() | b.keys())
    if not keys:
        return 1.0
    total = 0.0
    for k in keys:
        if k in a and k in b:
            num_a, va, ta = a[k]
            num_b, vb, tb = b[k]
            if num_a and num_b:
                if va == vb:
                    total += 1.0
                else:
                    value_range = ranges.get(k)
                    if value_range:
                        total += max(0.0, 1.0 - abs(float(va) - float(vb)) / value_range)
                    else:
                        total += 0.0
            else:
                total += 1.0 if ta == tb else 0.0
    return round(total / len(keys), 4)


@dataclass
class _Group:
    """Experiments with the same key set and the same (normalised) text values."""

    keys: frozenset[str]
    text: dict[str, str]  # text key → normalised value
    tokens: list[tuple[str, ...]]
    members: list[int] = field(default_factory=list)


def _groups(conds: dict[int, dict[str, Any]], text_keys: set[str]) -> list[_Group]:
    by_sig: dict[tuple[frozenset[str], tuple[tuple[str, str], ...]], _Group] = {}
    for eid in sorted(conds):
        c = conds[eid]
        text = {k: _norm_text(c[k]) for k in c if k in text_keys}
        sig = (frozenset(c), tuple(sorted(text.items())))
        g = by_sig.get(sig)
        if g is None:
            tokens: list[tuple[str, ...]] = [("t", k, v) for k, v in text.items()]
            tokens += [("k", k) for k in c if k not in text_keys]
            g = by_sig[sig] = _Group(keys=frozenset(c), text=text, tokens=tokens)
        g.members.append(eid)
    return list(by_sig.values())


def _candidate_groups(groups: list[_Group], t: float) -> set[tuple[int, int]]:
    """Index pairs ``(i, j)``, ``i <= j``, of groups that may share ≥ ``t`` of their keys.

    Prefix filter (set-similarity join): a pair can reach ``t`` only if the number of
    keys on which both agree (same text value, or both present for a non-text key) is
    at least ``ceil(t · |keys|)`` for *each* group — and two token sets with that
    overlap always share a token among the first ``|keys| − ceil(t · |keys|) + 1``
    tokens of a common global order.
    """
    freq: dict[tuple[str, ...], int] = {}
    for g in groups:
        for tok in g.tokens:
            freq[tok] = freq.get(tok, 0) + 1
    index: dict[tuple[str, ...], list[int]] = {}
    out: set[tuple[int, int]] = set()
    for gi, g in enumerate(groups):
        out.add((gi, gi))
        ordered = sorted(g.tokens, key=lambda tok: (freq[tok], tok))
        need = math.ceil(t * len(ordered) - 1e-9)
        for tok in ordered[: len(ordered) - need + 1]:
            for gj in index.setdefault(tok, []):
                out.add((gj, gi))
            index[tok].append(gi)
    return out


def similar_pairs(
    experiments: Sequence[ExperimentOut], threshold: float
) -> list[tuple[int, int, float]]:
    """All unordered pairs ``(id_lo, id_hi, score)`` with similarity ≥ ``threshold``.

    Same result as :func:`similar_pairs_bruteforce` (scores from
    :func:`_prepared_similarity`, bit-identical to :func:`similarity`), but pairs that
    provably cannot reach the threshold are never compared. With ``U`` = union of the
    two key sets, a key present on one side only or a text key with different values
    contributes 0, and a numeric key contributes
    ``1 − |Δ|/range``, so ``U − score·U`` ≥ (zero-contribution keys) + Σ |Δ|/range:

    1. experiments are grouped by key set + normalised text values (all pairs inside a
       group share every text value);
    2. group pairs come from a prefix-filtered inverted index over their keys/values, and a
       group pair is dropped when its zero-contribution keys alone exceed the budget
       ``(1 − t)·U``;
    3. inside a surviving group pair, the remaining budget bounds the summed normalised
       numeric distance, which is at least the distance of the members' summed normalised
       coordinates — a sort + window over that projection selects the pairs to score.
    """
    t = threshold - PRUNE_MARGIN
    if t <= 0:
        return similar_pairs_bruteforce(experiments, threshold)
    ranges = numeric_ranges(experiments)
    conds = {e.id: conditions(e) for e in experiments}
    numeric_keys: set[str] = set()
    other_keys: set[str] = set()
    for c in conds.values():
        for k, v in c.items():
            (numeric_keys if _is_number(v) else other_keys).add(k)
    text_keys = other_keys - numeric_keys  # never numeric → equality only
    plain_numeric = numeric_keys - other_keys  # numeric in every experiment that has it
    inexact = {
        k
        for c in conds.values()
        for k, v in c.items()
        if k in plain_numeric and not _exact_float(v)
    }
    # Projection axes: keys whose |Δ|/range bounds their score loss (finite values only).
    pure_numeric = {k for k in plain_numeric - inexact if ranges.get(k)}
    safe = not inexact  # every numeric value exactly representable → vectorised scoring
    groups = _groups(conds, text_keys)
    prepared = {eid: _prepare(c) for eid, c in conds.items()}

    scored: list[tuple[int, int, float]] = []

    def score(a: int, b: int) -> None:
        lo, hi = (a, b) if a < b else (b, a)
        value = _prepared_similarity(prepared[lo], prepared[hi], ranges)
        if value >= threshold:
            scored.append((lo, hi, value))

    for gi, gj in sorted(_candidate_groups(groups, t)):
        g, h = groups[gi], groups[gj]
        union = len(g.keys | h.keys)
        if union == 0:  # two empty blocks: similarity() is 1.0 by definition
            for i, a in enumerate(g.members):
                for b in g.members[i + 1 :] if gi == gj else h.members:
                    score(a, b)
            continue
        shared = g.keys & h.keys
        zero = len(g.keys ^ h.keys) + sum(
            1 for k in shared if k in text_keys and g.text[k] != h.text[k]
        )
        budget = (1 - t) * union - zero
        if budget < 0:
            continue
        axes = sorted(shared & pure_numeric)

        def proj(eid: int, axes: list[str] = axes) -> float:
            c = conds[eid]
            return sum(float(c[k]) / ranges[k] for k in axes)

        slack = budget + 1e-9
        pairs: list[tuple[int, int]] = []
        if gi == gj:
            pts = sorted((proj(e), e) for e in g.members)
            for i, (pa, a) in enumerate(pts):
                for pb, b in pts[i + 1 :]:
                    if pb - pa > slack:
                        break
                    pairs.append((a, b))
        else:
            other = sorted((proj(e), e) for e in h.members)
            keys = [p for p, _ in other]
            for a in g.members:
                pa = proj(a)
                lo = bisect.bisect_left(keys, pa - slack)
                hi = bisect.bisect_right(keys, pa + slack)
                pairs.extend((a, b) for _, b in other[lo:hi])
        if safe and shared <= text_keys | plain_numeric:
            scored.extend(
                _score_block(pairs, sorted(g.keys | h.keys), g, h, conds, ranges, threshold)
            )
        else:
            for a, b in pairs:
                score(a, b)
    scored.sort()
    return scored


def _exact_float(v: Any) -> bool:
    """``float(v)`` is exact and finite (so numpy reproduces Python's arithmetic on it)."""
    if isinstance(v, int):
        return abs(v) <= 2**53
    return math.isfinite(v)


def _score_block(
    pairs: list[tuple[int, int]],
    keys: list[str],
    g: _Group,
    h: _Group,
    conds: dict[int, dict[str, Any]],
    ranges: dict[str, float],
    threshold: float,
) -> list[tuple[int, int, float]]:
    """:func:`_prepared_similarity` of ``pairs`` (a in ``g``, b in ``h``), vectorised.

    Only for blocks whose shared keys are all text keys (constant per group) or
    always-numeric keys with exactly representable values. Per pair the same IEEE
    operations run in the same key order as the scalar code (``total += s`` over the
    sorted key union, then ``total / len(keys)``), and the 4-decimal rounding is Python's
    own ``round`` — so every score is bit-identical to :func:`similarity`.
    """
    if not pairs:
        return []
    a_ids = [a for a, _ in pairs]
    b_ids = [b for _, b in pairs]
    total = np.zeros(len(pairs))
    for k in keys:
        if k not in g.keys or k not in h.keys:
            continue  # missing on one side: contributes nothing
        if k in g.text:
            total += 1.0 if g.text[k] == h.text[k] else 0.0
            continue
        va = np.array([float(conds[i][k]) for i in a_ids])
        vb = np.array([float(conds[i][k]) for i in b_ids])
        value_range = ranges.get(k)
        if value_range:
            part = np.maximum(0.0, 1.0 - np.abs(va - vb) / value_range)
        else:
            part = np.zeros(len(pairs))
        total += np.where(va == vb, 1.0, part)
    mean = total / len(keys)
    out: list[tuple[int, int, float]] = []
    for idx in np.flatnonzero(mean >= threshold - PRUNE_MARGIN):
        value = round(float(mean[idx]), 4)
        if value >= threshold:
            a, b = a_ids[idx], b_ids[idx]
            out.append((a, b, value) if a < b else (b, a, value))
    return out


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
