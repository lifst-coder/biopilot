"""Failure causes (rule-based) and precedents ("we saw this before, and decided …").

Partner interprets; it never computes numbers. The failure list, failure types and
repeat patterns come from Memory (:func:`app.memory.service.failure_archive`), every
recovery value and QC status is copied from Analysis (:func:`analysis.get_metrics`),
and decisions/hypotheses are Partner's own stored records.

Cause rules (each names the experiments it read)
    ``initial_conditions``      the root experiment already failed — no baseline
    ``outside_condition_block`` identical conditions to the parent — something not in
                                the condition block (reagent, hands, instrument)
    ``confounded_change``       several keys changed at once — not separable
    ``changed_condition``       one changed key (per change)
    ``repeated_value``          the same value failed again (Memory pattern link)
    ``used_elsewhere``          another project used exactly this value without failing
    ``operator_change``         a different person than the parent experiment
    ``note_reagent`` / ``note_instrument``  the original note mentions reagent lots /
                                instrument state (the note line is quoted)

Precedents
    For an experiment that failed, earlier failures (any project) with the same
    symptom: the same condition key changed (``same_change``; ``same_value`` when the
    new value is identical), the same analytes missed in the same project
    (``same_analytes``) or both failing without any condition change (``no_change``).
    For each, the decisions recorded on it, the resolving experiment of its pattern
    and its stored hypotheses — "그때 이렇게 결론 내렸다".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.eln import service as eln
from app.eln.schemas import CONDITION_FIELD_LABELS, ExperimentOut
from app.memory import service as memory
from app.memory.schemas import ConditionChange, FailureArchive, FailureRecord
from app.partner import service
from app.partner.schemas import (
    ConditionUsage,
    DecisionLink,
    ExperimentRef,
    FailureArchiveOut,
    FailureCause,
    FailureExplanation,
    FollowUpExperiment,
    PrecedentCase,
    PrecedentMatch,
    PrecedentsOut,
    ProposalChange,
    StoredHypothesisRef,
)

#: Note keywords → rule. Matching is a plain substring test on each note line.
REAGENT_WORDS = ("lot", "흡습", "개봉", "시약", "유효기간")
INSTRUMENT_WORDS = ("점검", "오염", "이온원", "배압", "압력", "감도")
MAX_PRECEDENTS = 3


def _label(key: str) -> str:
    return CONDITION_FIELD_LABELS.get(key, key)


def _value(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "없음" if v is None else str(v)


def _cond(exp: ExperimentOut) -> dict[str, Any]:
    return exp.condition_block.model_dump(exclude_none=True)


@dataclass
class _World:
    """Everything the rules read, loaded once per request."""

    archive: FailureArchive
    experiments: dict[int, ExperimentOut]
    project_names: dict[int, str]

    @property
    def failures(self) -> dict[int, FailureRecord]:
        return {f.experiment.id: f for f in self.archive.failures}


def _world(session: Session, project_ids: list[int] | None = None) -> _World:
    projects = eln.list_projects(session)
    archive = memory.failure_archive(session, project_ids)
    experiments = {e.id: e for p in projects for e in eln.list_experiments_full(session, p.id)}
    return _World(
        archive=archive, experiments=experiments, project_names={p.id: p.name for p in projects}
    )


def _follow(session: Session, exp: ExperimentOut) -> FollowUpExperiment:
    m = analysis.get_metrics(session, exp.id)
    return FollowUpExperiment(
        experiment_id=exp.id,
        code=exp.code,
        title=exp.title,
        qc_status=m.qc_status,
        recovery_mean_pct=m.recovery_mean_pct,
        source_result_ids=m.source_result_ids,
    )


# ------------------------------------------------------------------ causes


def _note_causes(exp: ExperimentOut) -> list[FailureCause]:
    out: list[FailureCause] = []
    for rule, words, what in (
        ("note_reagent", REAGENT_WORDS, "시약 상태"),
        ("note_instrument", INSTRUMENT_WORDS, "기기 상태"),
    ):
        for line in exp.raw_note.splitlines():
            text = line.strip().lstrip("-").strip()
            if text and any(w in text.lower() for w in words):
                out.append(
                    FailureCause(
                        rule=rule,
                        statement=(
                            f"원본 메모에 {what}에 관한 기록이 있다 — 조건 블록 밖의 원인 후보"
                        ),
                        experiment_ids=[exp.id],
                        note_excerpt=text,
                    )
                )
                break
    return out


def _change_text(c: ConditionChange) -> str:
    if c.change == "added":
        return f"{_label(c.key)} {_value(c.value_b)} 추가"
    if c.change == "removed":
        return f"{_label(c.key)} {_value(c.value_a)} 제거"
    return f"{_label(c.key)} {_value(c.value_a)} → {_value(c.value_b)}"


def causes(session: Session, world: _World, record: FailureRecord) -> list[FailureCause]:
    """Rule-based cause hypotheses of one failure, each with its evidence experiments."""
    exp = world.experiments[record.experiment.id]
    parent = world.experiments.get(record.parent.id) if record.parent else None
    out: list[FailureCause] = []
    if parent is None:
        out.append(
            FailureCause(
                rule="initial_conditions",
                statement=(
                    "첫 조건부터 기준 미달 — 비교할 기준선이 없어 "
                    "조건 자체(컬럼·용매·정제)를 다시 봐야 한다"
                ),
                experiment_ids=[exp.id],
            )
        )
    elif not record.changes:
        out.append(
            FailureCause(
                rule="outside_condition_block",
                statement=(
                    f"부모 {parent.code}와 조건 블록이 같다 — 조건 블록에 기록되지 않는 요인"
                    "(시약 상태·작업자 손기술·기기 상태)이 원인 후보"
                ),
                experiment_ids=[parent.id, exp.id],
            )
        )
    else:
        if len(record.changes) > 1:
            out.append(
                FailureCause(
                    rule="confounded_change",
                    statement=(
                        f"{len(record.changes)}개 조건("
                        + ", ".join(_label(c.key) for c in record.changes)
                        + ")을 한 번에 바꿔 어느 변경 때문인지 이 실험만으로는 분리할 수 없다"
                    ),
                    experiment_ids=[parent.id, exp.id],
                )
            )
        for c in record.changes:
            out.append(
                FailureCause(
                    rule="changed_condition",
                    statement=f"{_change_text(c)} 변경이 원인 후보",
                    experiment_ids=[parent.id, exp.id],
                )
            )
    for p in world.archive.patterns:
        for link in p.links:
            if link.kind != "same_condition" or exp.id not in (
                link.from_experiment_id,
                link.to_experiment_id,
            ):
                continue
            other = (
                link.to_experiment_id
                if link.from_experiment_id == exp.id
                else link.from_experiment_id
            )
            out.append(
                FailureCause(
                    rule="repeated_value",
                    statement=(
                        f"같은 {link.label or link.key} 값({_value(link.value)})에서 "
                        f"{world.experiments[other].code}도 실패 — 같은 분석물"
                        f"({', '.join(link.shared_analytes)}) 미달"
                    ),
                    experiment_ids=sorted({link.from_experiment_id, link.to_experiment_id}),
                )
            )
    for usage in condition_usage(session, world, exp, record.changes):
        if usage.fail_count:
            continue
        out.append(
            FailureCause(
                rule="used_elsewhere",
                statement=(
                    f"{usage.project_name}에서는 같은 {usage.label}({_value(usage.value)})로 "
                    f"실패하지 않았다 — 이 프로젝트 분석물에 맞지 않는 조건일 수 있다"
                ),
                experiment_ids=[x.experiment_id for x in usage.experiments],
            )
        )
    if parent is not None and parent.author != exp.author:
        out.append(
            FailureCause(
                rule="operator_change",
                statement=f"작업자가 부모 실험과 다르다 ({parent.author} → {exp.author})",
                experiment_ids=[parent.id, exp.id],
            )
        )
    out.extend(_note_causes(exp))
    for cause in out:
        cause.experiments = [
            ExperimentRef(
                id=i, code=world.experiments[i].code, project_id=world.experiments[i].project_id
            )
            for i in cause.experiment_ids
            if i in world.experiments
        ]
    return out


# ------------------------------------------------------- decisions & usage


def _follow_up(
    session: Session,
    world: _World,
    base: ExperimentOut,
    changes: list[ProposalChange],
    before: tuple[date, int] | None = None,
) -> FollowUpExperiment | None:
    """Earliest later experiment of the project applying every condition-key change."""
    known = {k for e in world.experiments.values() for k in _cond(e)}
    wanted = [c for c in changes if c.key in known]
    if not wanted:
        return None
    later = sorted(
        (
            e
            for e in world.experiments.values()
            if e.project_id == base.project_id
            and (e.performed_on, e.id) > (base.performed_on, base.id)
            and (before is None or (e.performed_on, e.id) < before)
        ),
        key=lambda e: (e.performed_on, e.id),
    )
    for e in later:
        cond = _cond(e)
        if all(c.key in cond and _value(cond[c.key]) == _value(c.value) for c in wanted):
            return _follow(session, e)
    return None


def decisions(
    session: Session, world: _World, experiment_id: int, before: tuple[date, int] | None = None
) -> list[DecisionLink]:
    """Decisions recorded on proposals made for ``experiment_id`` (oldest first).

    ``before``: only follow-up experiments performed before this ``(date, id)`` are
    linked (a precedent shows what was known when the later experiment was run).
    """
    exp = world.experiments[experiment_id]
    history = service.decision_history(session, exp.project_id, experiment_id)
    out: list[DecisionLink] = []
    for entry in reversed(history.entries):
        d = entry.decision
        applied = d.modifications or entry.proposal_changes
        out.append(
            DecisionLink(
                decision_id=d.id,
                proposal_id=entry.proposal_id,
                proposal_title=entry.proposal_title,
                action=d.action,
                reason_category=d.reason_category,
                rationale=d.rationale,
                decided_by=d.decided_by,
                changes=applied,
                follow_up=_follow_up(session, world, exp, applied, before)
                if d.action != "reject"
                else None,
            )
        )
    return out


def _hypotheses(session: Session, exp: ExperimentOut) -> list[StoredHypothesisRef]:
    """Stored hypotheses of an experiment, one per statement (re-critiques repeat them)."""
    seen: dict[str, StoredHypothesisRef] = {}
    for h in service.list_hypotheses(session, exp.project_id, exp.id):
        seen[h.statement] = StoredHypothesisRef(id=h.id, statement=h.statement, status=h.status)
    return list(seen.values())


def condition_usage(
    session: Session, world: _World, exp: ExperimentOut, changes: list[ConditionChange]
) -> list[ConditionUsage]:
    """Earlier experiments of *other* projects using exactly a value ``exp`` changed to.

    Only categorical (text) values: a reagent, sorbent or column means the same thing in
    every project, a number (15 min, 10 g) coinciding across matrices does not.
    """
    out: list[ConditionUsage] = []
    for c in changes:
        if c.change == "removed" or not isinstance(c.value_b, str):
            continue
        by_project: dict[int, list[ExperimentOut]] = {}
        for e in world.experiments.values():
            if e.project_id == exp.project_id or e.performed_on > exp.performed_on:
                continue
            cond = _cond(e)
            if c.key in cond and _value(cond[c.key]) == _value(c.value_b):
                by_project.setdefault(e.project_id, []).append(e)
        for pid, members in sorted(by_project.items()):
            members.sort(key=lambda e: (e.performed_on, e.id))
            rows = [_follow(session, e) for e in members]
            out.append(
                ConditionUsage(
                    key=c.key,
                    label=_label(c.key),
                    value=c.value_b,
                    project_id=pid,
                    project_name=world.project_names.get(pid, str(pid)),
                    experiments=rows,
                    fail_count=sum(1 for r in rows if r.qc_status == "fail"),
                    analyzed_count=sum(1 for r in rows if r.qc_status != "not_analyzed"),
                )
            )
    return out


# ---------------------------------------------------------------- archive


def failure_archive(session: Session, project_ids: list[int] | None = None) -> FailureArchiveOut:
    """Memory's archive with Partner's rule-based causes and linked decisions."""
    world = _world(session, project_ids)
    explanations = [
        FailureExplanation(
            experiment_id=r.experiment.id,
            causes=causes(session, world, r),
            hypotheses=_hypotheses(session, world.experiments[r.experiment.id]),
            decisions=decisions(session, world, r.experiment.id),
        )
        for r in world.archive.failures
    ]
    return FailureArchiveOut(archive=world.archive, explanations=explanations)


# ------------------------------------------------------------- precedents


def _matches(target: FailureRecord, past: FailureRecord) -> list[PrecedentMatch]:
    out: list[PrecedentMatch] = []
    mine = {c.key: c for c in target.changes if c.change != "removed"}
    for c in past.changes:
        if c.key not in mine:
            continue
        same = _value(mine[c.key].value_b) == _value(c.value_b)
        out.append(
            PrecedentMatch(
                kind="same_value" if same else "same_change",
                label=(
                    f"같은 {_label(c.key)} 값으로 변경 ({_value(c.value_b)})"
                    if same
                    else f"{_label(c.key)} 변경 후 실패 ({_value(c.value_a)} → {_value(c.value_b)})"
                ),
                key=c.key,
                value=_value(c.value_b),
            )
        )
    if target.experiment.project_id == past.experiment.project_id:
        shared = sorted(set(target.failed_analytes) & set(past.failed_analytes))
        if shared:
            out.append(
                PrecedentMatch(
                    kind="same_analytes",
                    label="같은 분석물 미달: " + ", ".join(shared),
                    analytes=shared,
                )
            )
    if target.parent and past.parent and not target.changes and not past.changes:
        out.append(PrecedentMatch(kind="no_change", label="부모와 같은 조건에서 실패 (재현 실패)"))
    return out


_SCORES = {"same_value": 3, "same_change": 2, "no_change": 2, "same_analytes": 1}


def _resolution(
    session: Session, world: _World, experiment_id: int, before: tuple[date, int]
) -> FollowUpExperiment | None:
    """Resolving experiment of the failure's pattern, if it happened before ``before``."""
    for p in world.archive.patterns:
        if experiment_id in p.experiment_ids and p.resolution is not None:
            res = world.experiments[p.resolution.id]
            if (res.performed_on, res.id) < before:
                return _follow(session, res)
    return None


def precedents(session: Session, experiment_id: int) -> PrecedentsOut:
    """Earlier same-symptom failures (any project) and what was concluded then."""
    world = _world(session)
    exp = world.experiments.get(experiment_id) or eln.get_experiment(session, experiment_id)
    failures = world.failures
    target = failures.get(experiment_id)
    if target is None:  # no failure → no symptom to look up
        return PrecedentsOut(
            experiment_id=experiment_id, failed=False, failed_analytes=[], changed_keys=[], cases=[]
        )
    cutoff: tuple[date, int] = (exp.performed_on, exp.id)
    cases: list[PrecedentCase] = []
    for past in failures.values():
        if (past.experiment.performed_on, past.experiment.id) >= cutoff:
            continue
        matched = _matches(target, past)
        if not matched:
            continue
        pexp = world.experiments[past.experiment.id]
        m = analysis.get_metrics(session, pexp.id)
        cases.append(
            PrecedentCase(
                experiment=past.experiment,
                project_name=past.project_name,
                failed_analytes=past.failed_analytes,
                recovery_mean_pct=m.recovery_mean_pct,
                source_result_ids=m.source_result_ids,
                matches=matched,
                score=sum(_SCORES[x.kind] for x in matched),
                decisions=decisions(session, world, pexp.id, cutoff),
                resolution=_resolution(session, world, pexp.id, cutoff),
                hypotheses=_hypotheses(session, pexp),
            )
        )
    cases.sort(key=lambda c: (-c.score, -c.experiment.performed_on.toordinal(), -c.experiment.id))
    return PrecedentsOut(
        experiment_id=experiment_id,
        failed=True,
        failed_analytes=target.failed_analytes,
        changed_keys=[c.key for c in target.changes],
        cases=cases[:MAX_PRECEDENTS],
        condition_usage=condition_usage(session, world, exp, target.changes),
    )
