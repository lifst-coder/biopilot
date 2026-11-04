"""Records across projects: stored outcomes grouped by condition value, author and month.

Every number is read from stored results (:func:`service.get_metrics_many`) or computed here
deterministically from them (count, min/median/max, fail ratio); author differences use
the existing comparison (:func:`service.compare`, Welch t-test). No new analytical
metric is introduced and nothing is interpreted.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.analysis import service
from app.analysis.schemas import (
    ConditionRecords,
    OperatorPair,
    OperatorRecords,
    PeriodRecords,
    RecordExperiment,
    RecordGap,
    RecordGroup,
)
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.schemas import ExperimentOut

#: Default: two people running the same protocol within this many days count as a pair.
OPERATOR_WINDOW_DAYS = 14
#: Default: a stretch of at least this many days without any experiment is a gap.
GAP_DAYS = 21
NO_VALUE = "(값 없음)"


@dataclass(frozen=True)
class _Row:
    exp: ExperimentOut
    record: RecordExperiment


def _project_ids(session: Session, project_ids: Iterable[int] | None) -> list[int]:
    known = [p.id for p in eln.list_projects(session)]
    if project_ids is None:
        return known
    wanted = set(project_ids)
    missing = sorted(wanted - set(known))
    if missing:
        raise NotFoundError(f"project {missing[0]} not found")
    return [p for p in known if p in wanted]


def _rows(session: Session, project_ids: list[int]) -> list[_Row]:
    """Every experiment of the projects with its stored headline metrics.

    Batched: one experiment listing per project and one result query per 500
    experiments (:func:`service.get_metrics_many`) — not a lookup per experiment.
    """
    rows: list[_Row] = []
    for pid in project_ids:
        exps = eln.list_experiments_full(session, pid)
        metrics = service.get_metrics_many(session, [e.id for e in exps])
        for exp in exps:
            m = metrics[exp.id]
            rows.append(
                _Row(
                    exp=exp,
                    record=RecordExperiment(
                        experiment_id=exp.id,
                        project_id=exp.project_id,
                        code=exp.code,
                        title=exp.title,
                        author=exp.author,
                        performed_on=exp.performed_on,
                        recovery_mean_pct=m.recovery_mean_pct,
                        recovery_rsd_pct=m.recovery_rsd_pct,
                        qc_status=m.qc_status,
                        source_result_ids=m.source_result_ids,
                    ),
                )
            )
    rows.sort(key=lambda r: (r.exp.performed_on, r.exp.id))
    return rows


def group(key: str, members: list[RecordExperiment], value: Any = None) -> RecordGroup:
    """Summary of one group (count, stored-recovery min/median/max, QC fail ratio)."""
    recoveries = [m.recovery_mean_pct for m in members if m.recovery_mean_pct is not None]
    analyzed = sum(1 for m in members if m.qc_status != "not_analyzed")
    fails = sum(1 for m in members if m.qc_status == "fail")
    return RecordGroup(
        key=key,
        value=value,
        experiments=members,
        experiment_count=len(members),
        analyzed_count=analyzed,
        recovery_n=len(recoveries),
        recovery_min_pct=min(recoveries) if recoveries else None,
        recovery_median_pct=float(statistics.median(recoveries)) if recoveries else None,
        recovery_max_pct=max(recoveries) if recoveries else None,
        fail_count=fails,
        fail_ratio=fails / analyzed if analyzed else None,
    )


def _display(value: Any) -> str:
    if value is None:
        return NO_VALUE
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _grouped(rows: list[_Row], key_of: Callable[[_Row], tuple[str, Any]]) -> list[RecordGroup]:
    buckets: dict[str, tuple[Any, list[RecordExperiment]]] = {}
    for r in rows:
        k, v = key_of(r)
        buckets.setdefault(k, (v, []))[1].append(r.record)
    return [group(k, members, v) for k, (v, members) in buckets.items()]


def _conditions(exp: ExperimentOut) -> dict[str, Any]:
    return exp.condition_block.model_dump(exclude_none=True)


def by_condition(
    session: Session,
    key: str,
    project_ids: Iterable[int] | None = None,
    contains: str | None = None,
) -> ConditionRecords:
    """Experiments grouped by the value of condition ``key``; optionally pooled by substring."""
    pids = _project_ids(session, project_ids)
    rows = _rows(session, pids)

    def key_of(r: _Row) -> tuple[str, Any]:
        value = _conditions(r.exp).get(key)
        return _display(value), value

    groups = _grouped(rows, key_of)
    groups.sort(key=lambda g: (g.key == NO_VALUE, -g.experiment_count, g.key))
    needle = (contains or "").strip().lower()
    matched = None
    if needle:
        members = [
            r.record
            for r in rows
            if key in _conditions(r.exp) and needle in _display(_conditions(r.exp)[key]).lower()
        ]
        matched = group(f"'{contains}' 포함", members)
    return ConditionRecords(
        key=key, project_ids=pids, contains=contains or None, groups=groups, matched=matched
    )


def by_operator(
    session: Session,
    project_ids: Iterable[int] | None = None,
    window_days: int = OPERATOR_WINDOW_DAYS,
) -> OperatorRecords:
    """Author groups, and same-protocol pairs run by different authors within a window."""
    pids = _project_ids(session, project_ids)
    rows = _rows(session, pids)
    authors = _grouped(rows, lambda r: (r.exp.author, r.exp.author))
    authors.sort(key=lambda g: g.key)
    pairs: list[OperatorPair] = []
    with_recovery = [r for r in rows if r.record.recovery_mean_pct is not None]
    for i, a in enumerate(with_recovery):
        for b in with_recovery[i + 1 :]:
            if a.exp.project_id != b.exp.project_id or a.exp.author == b.exp.author:
                continue
            days = abs((b.exp.performed_on - a.exp.performed_on).days)
            if days > window_days:
                continue
            cond_a, cond_b = _conditions(a.exp), _conditions(b.exp)
            if cond_a != cond_b:
                continue
            cmp = service.compare(session, a.exp.id, b.exp.id)
            p = cmp.recovery_t_test.p_value if cmp.recovery_t_test else None
            pairs.append(
                OperatorPair(
                    experiment_a=a.record,
                    experiment_b=b.record,
                    days_apart=days,
                    condition_key_count=len(cond_a),
                    recovery_delta_pct_points=cmp.recovery_delta_pct_points,
                    p_value=p,
                    alpha=cmp.alpha,
                    significant=(p < cmp.alpha) if p is not None else None,
                    significant_analytes=cmp.significant_analytes,
                )
            )
    pairs.sort(
        key=lambda x: (
            -abs(x.recovery_delta_pct_points or 0.0),
            x.experiment_a.experiment_id,
            x.experiment_b.experiment_id,
        )
    )
    return OperatorRecords(project_ids=pids, window_days=window_days, authors=authors, pairs=pairs)


def by_period(
    session: Session,
    project_ids: Iterable[int] | None = None,
    gap_days: int = GAP_DAYS,
) -> PeriodRecords:
    """Monthly groups and stretches of ≥ ``gap_days`` without any experiment."""
    pids = _project_ids(session, project_ids)
    rows = _rows(session, pids)
    months = _grouped(rows, lambda r: (r.exp.performed_on.strftime("%Y-%m"), None))
    months.sort(key=lambda g: g.key)
    dates = sorted({r.exp.performed_on for r in rows})
    gaps: list[RecordGap] = []
    for start, end in itertools.pairwise(dates):
        days = (end - start).days
        if days >= gap_days:
            gaps.append(
                RecordGap(
                    start=start,
                    end=end,
                    days=days,
                    before=[r.record for r in rows if r.exp.performed_on == start],
                    after=[r.record for r in rows if r.exp.performed_on == end],
                )
            )
    return PeriodRecords(project_ids=pids, gap_days=gap_days, months=months, gaps=gaps)
