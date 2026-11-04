"""Pre-optimisation implementations — the reference the optimised code must match.

Copied verbatim (modulo names) from commit ``07dd14e`` — the state measured in the first
PERFORMANCE.md report — for every function the performance work changed. Used only by
``tests/test_perf_equivalence.py``, which swaps them in with ``monkeypatch`` and checks
that every affected endpoint answers byte-for-byte the same as with the optimised code.

Nothing here is used by the application.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from typing import Any

import numpy as np
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import wiring
from app.analysis import calculations as calc
from app.analysis import records
from app.analysis import service as analysis
from app.analysis.criteria import overall_status, verdicts
from app.analysis.schemas import (
    AnalysisResultOut,
    AnalyteLimitsSummary,
    AnalyteRecoverySummary,
    CalibrationOutput,
    ExperimentMetrics,
    IonRatioOutput,
    ISResponseOutput,
    LimitsOutput,
    MatrixEffectOutput,
    RecordExperiment,
    RecoveryOutput,
    ResultKind,
)
from app.core.errors import NotFoundError
from app.eln import service as eln
from app.eln.models import (
    AttachmentFile,
    Experiment,
    ExperimentAddendum,
    ExperimentRevision,
)
from app.eln.schemas import (
    Attachment,
    ConditionBlock,
    DatasetKind,
    ExperimentAddendumOut,
    ExperimentOut,
)
from app.memory import conditions as mem_conditions
from app.memory import facts, failures, knowledge_graph, ports, search_index
from app.memory import service as memory
from app.memory.models import IndexState
from app.memory.schemas import (
    EntityFacts,
    FactProvider,
    FailurePatternLink,
    QCFact,
    ResultFact,
    SourceRef,
)

# ------------------------------------------------------------------ eln


def _ref_to_out(session: Session, exp: Experiment, kinds: list[DatasetKind]) -> ExperimentOut:
    addenda = session.scalars(
        select(ExperimentAddendum)
        .where(ExperimentAddendum.experiment_id == exp.id)
        .order_by(ExperimentAddendum.id)
    )
    files = session.scalars(
        select(AttachmentFile)
        .where(AttachmentFile.experiment_id == exp.id)
        .order_by(AttachmentFile.id)
    )
    count = session.scalar(
        select(func.count())
        .select_from(ExperimentRevision)
        .where(ExperimentRevision.experiment_id == exp.id)
    )
    return ExperimentOut(
        id=exp.id,
        project_id=exp.project_id,
        code=exp.code,
        title=exp.title,
        author=exp.author,
        performed_on=exp.performed_on,
        parent_experiment_id=exp.parent_experiment_id,
        dataset_kinds=kinds,
        raw_note=exp.raw_note,
        condition_block=ConditionBlock.model_validate(exp.condition_block),
        attachments=[Attachment.model_validate(a) for a in exp.attachments],
        created_at=exp.created_at,
        cloned_from_experiment_id=exp.cloned_from_experiment_id,
        protocol_template_id=exp.protocol_template_id,
        revision=1 + (count or 0),
        addenda=[ExperimentAddendumOut.model_validate(a) for a in addenda],
        attachment_files=[eln._file_out(f) for f in files],
    )


def ref_list_experiments_full(session: Session, project_id: int) -> list[ExperimentOut]:
    """Per-experiment queries (revision count, addenda, files for each experiment)."""
    eln.get_project(session, project_id)
    exps = list(
        session.scalars(
            select(Experiment)
            .where(Experiment.project_id == project_id)
            .order_by(Experiment.performed_on, Experiment.code)
        )
    )
    kinds = eln._dataset_kinds(session, [e.id for e in exps])
    return [_ref_to_out(session, e, kinds.get(e.id, [])) for e in exps]


# ------------------------------------------------------------- analysis


def ref_get_metrics(session: Session, experiment_id: int) -> ExperimentMetrics:
    """Headline metrics from fully validated ``AnalysisResultOut`` (``latest_results``)."""
    eln.get_experiment(session, experiment_id)
    latest = analysis.latest_results(session, experiment_id)
    if not latest:
        return ExperimentMetrics(experiment_id=experiment_id, analyzed=False)
    flags = [f for r in latest.values() for f in r.flags]
    m = ExperimentMetrics(
        experiment_id=experiment_id,
        analyzed=True,
        source_result_ids=sorted(r.id for r in latest.values()),
        flags=flags,
        qc_status=overall_status(flags),
        criteria_versions=sorted(
            {
                str(r.parameters["criteria_version"])
                for r in latest.values()
                if "criteria_version" in r.parameters
            }
        ),
    )
    analytes: set[str] = {f.analyte for f in flags if f.analyte}
    if (rec := latest.get("recovery")) and isinstance(rec.output, RecoveryOutput):
        m.recovery_mean_pct = rec.output.overall_mean_pct
        m.recovery_rsd_pct = rec.output.overall_rsd_pct
        m.recovery_n = rec.output.n
        for analyte in sorted({r.analyte for r in rec.output.rows}):
            vals = np.array([r.recovery_pct for r in rec.output.rows if r.analyte == analyte])
            mean, _sd, rsd = calc.summary_stats(vals)
            m.per_analyte_recovery.append(
                AnalyteRecoverySummary(analyte=analyte, mean_pct=mean, rsd_pct=rsd, n=vals.size)
            )
            analytes.add(analyte)
        m.expanded_uncertainty_pct = {u.analyte: u.expanded_pct for u in rec.output.uncertainty}
        m.outlier_count = sum(1 for g in rec.output.groups if g.grubbs and g.grubbs.is_outlier)
    if (cal := latest.get("calibration")) and isinstance(cal.output, CalibrationOutput):
        m.min_r_squared = min(a.r_squared for a in cal.output.analytes)
        m.max_abs_back_calc_error_pct = max(
            a.max_abs_back_calc_error_pct for a in cal.output.analytes
        )
        m.calibration_weighting = cal.output.weighting
        analytes.update(a.analyte for a in cal.output.analytes)
    if (isr := latest.get("is_response")) and isinstance(isr.output, ISResponseOutput):
        m.is_injections_total = len(isr.output.injections)
        m.is_injections_flagged = isr.output.flagged_count
    if (me := latest.get("matrix_effect")) and isinstance(me.output, MatrixEffectOutput):
        m.matrix_effect_pct = {a.analyte: a.matrix_effect_pct for a in me.output.analytes}
        analytes.update(m.matrix_effect_pct)
    if (lim := latest.get("limits")) and isinstance(lim.output, LimitsOutput):
        m.limits = [
            AnalyteLimitsSummary(
                analyte=a.analyte,
                lod=a.lod,
                loq=a.loq,
                unit=lim.output.unit,
                method=a.primary_method,
            )
            for a in lim.output.analytes
        ]
    if (ion := latest.get("ion_ratio")) and isinstance(ion.output, IonRatioOutput):
        m.ion_ratio_injections_flagged = ion.output.flagged_count
    m.qc_verdicts = verdicts(analytes, flags)
    return m


def ref_records_rows(session: Session, project_ids: list[int]) -> list[Any]:
    """One ``get_metrics`` per experiment."""
    rows: list[Any] = []
    for pid in project_ids:
        for exp in eln.list_experiments_full(session, pid):
            m = analysis.get_metrics(session, exp.id)
            rows.append(
                records._Row(
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


# --------------------------------------------------------------- wiring


class RefAnalysisFactProvider(wiring.AnalysisFactProvider):
    """The analysis fact provider before batching: full results per experiment.

    ``results`` / ``describe`` select which halves are reverted (both by default).
    """

    def __init__(self, *, results: bool = True, describe: bool = True) -> None:
        self.revert_results = results
        self.revert_describe = describe

    def results(self, session: Session, experiment_id: int) -> list[ResultFact]:
        if not self.revert_results:
            return super().results(session, experiment_id)
        m = analysis.get_metrics(session, experiment_id)
        latest = analysis.latest_results(session, experiment_id)
        out: list[ResultFact] = []

        def add(
            kind: ResultKind,
            metric: str,
            lbl: str,
            value: float | None,
            unit: str | None,
            field: str,
            analyte: str | None = None,
        ) -> None:
            res = latest.get(kind)
            if res is None or value is None:
                return
            out.append(
                ResultFact(
                    metric=metric,
                    label=lbl,
                    analyte=analyte,
                    value=value,
                    unit=unit,
                    source=wiring._src(res, field, experiment_id)[0],
                )
            )

        add("recovery", "recovery_mean_pct", "평균 회수율", m.recovery_mean_pct, "%",
            "output.overall_mean_pct")  # fmt: skip
        add("recovery", "recovery_rsd_pct", "회수율 RSD", m.recovery_rsd_pct, "%",
            "output.overall_rsd_pct")  # fmt: skip
        for a in m.per_analyte_recovery:
            add("recovery", "analyte_recovery_mean_pct", f"{a.analyte} 평균 회수율", a.mean_pct,
                "%", f"output.rows[analyte={a.analyte}].recovery_pct", a.analyte)  # fmt: skip
        add("calibration", "min_r_squared", "최소 R²", m.min_r_squared, None,
            "output.analytes[].r_squared")  # fmt: skip
        if m.is_injections_flagged is not None:
            add("is_response", "is_injections_flagged", "IS 이상 주입 수",
                float(m.is_injections_flagged), "회", "output.flagged_count")  # fmt: skip
        for analyte, me in m.matrix_effect_pct.items():
            add("matrix_effect", "matrix_effect_pct", f"{analyte} 매트릭스 효과", me, "%",
                f"output.analytes[analyte={analyte}].matrix_effect_pct", analyte)  # fmt: skip
        return out

    def results_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[ResultFact]]:
        if not self.revert_results:
            return super().results_many(session, experiment_ids)
        return FactProvider.results_many(self, session, experiment_ids)

    def facts_many(
        self, session: Session, experiment_ids: list[int]
    ) -> tuple[dict[int, list[ResultFact]], dict[int, list[QCFact] | None]]:
        if not self.revert_results:
            return super().facts_many(session, experiment_ids)
        return FactProvider.facts_many(self, session, experiment_ids)

    def qc_flags(self, session: Session, experiment_id: int) -> list[QCFact] | None:
        if not self.revert_results:
            return super().qc_flags(session, experiment_id)
        out: list[QCFact] = []
        for res in analysis.latest_results(session, experiment_id).values():
            for i, f in enumerate(res.flags):
                out.append(
                    QCFact(
                        code=f.code,
                        severity=f.severity,
                        analyte=f.analyte,
                        value=f.value,
                        context=f.context,
                        source=SourceRef(
                            ref_type=wiring.RESULT_REF,
                            ref_id=res.id,
                            field=f"flags[{i}]",
                            experiment_id=experiment_id,
                        ),
                    )
                )
        return out

    def qc_flags_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[QCFact] | None]:
        if not self.revert_results:
            return super().qc_flags_many(session, experiment_ids)
        return FactProvider.qc_flags_many(self, session, experiment_ids)

    def describe(
        self,
        session: Session,
        ref_type: str,
        ref_id: int,
        project_id: int,
        payload: dict[str, Any],
    ) -> EntityFacts | None:
        if not self.revert_describe:
            return super().describe(session, ref_type, ref_id, project_id, payload)
        if ref_type != wiring.RESULT_REF:
            return None
        try:
            res: AnalysisResultOut = analysis.get_result(session, ref_id)
        except NotFoundError:
            return None
        return EntityFacts(
            ref_type=ref_type,
            ref_id=ref_id,
            label=f"{wiring._KIND_LABELS.get(res.kind, res.kind)} 결과 ({res.method_version})",
            experiment_id=res.experiment_id,
            kind=res.kind,
            flagged_analytes=sorted({f.analyte for f in res.flags if f.analyte}),
        )

    def describe_many(
        self,
        session: Session,
        ref_type: str,
        items: list[tuple[int, dict[str, Any]]],
        project_id: int,
    ) -> list[EntityFacts | None]:
        if not self.revert_describe:
            return super().describe_many(session, ref_type, items, project_id)
        return FactProvider.describe_many(self, session, ref_type, items, project_id)


# --------------------------------------------------------------- memory


def ref_changed_keys(a: ExperimentOut, b: ExperimentOut) -> list[str]:
    """Keys via full ``ConditionChange`` records."""
    return [c.key for c in mem_conditions.condition_changes(a, b)]


def ref_dataset_vocab(session: Session, dataset_id: int) -> facts.DatasetVocab:
    """Metadata lookup per call, CSV parsed once per process (cached by sha256)."""
    meta = eln.get_dataset(session, dataset_id)
    key = (dataset_id, meta.sha256)
    if key in facts._dataset_cache:
        return facts._dataset_cache[key]
    analytes: list[str] = []
    samples: list[str] = []
    reader = csv.DictReader(io.StringIO(eln.get_dataset_content(session, dataset_id)))
    for row in reader:
        a, s = (row.get("analyte") or "").strip(), (row.get("sample_id") or "").strip()
        if a and a not in analytes:
            analytes.append(a)
        if s and s not in samples:
            samples.append(s)
    vocab = facts.DatasetVocab(
        dataset_id=dataset_id, analytes=tuple(analytes), samples=tuple(samples)
    )
    facts._dataset_cache[key] = vocab
    return vocab


def _ref_vocab_any_meta(session: Session, dataset_id: int, meta: Any = None) -> facts.DatasetVocab:
    return ref_dataset_vocab(session, dataset_id)


def ref_experiment_vocab(session: Session, exp: ExperimentOut) -> facts.ExperimentVocab:
    """Vocabulary of one experiment: its datasets listed and parsed one by one."""
    vocab = facts.ExperimentVocab(experiment_id=exp.id)
    for key, value in mem_conditions.conditions(exp).items():
        txt = mem_conditions.display(value)
        if key in mem_conditions.SAMPLE_KEYS:
            vocab.samples[txt] = f"condition_block.{key}"
        if key in mem_conditions.STRAIN_KEYS:
            vocab.strains[txt] = f"condition_block.{key}"
        vocab.conditions[f"{mem_conditions.label(key)}: {txt}"] = key
    for ds in eln.list_datasets(session, exp.id):
        dv = ref_dataset_vocab(session, ds.id)
        for a in dv.analytes:
            vocab.analytes.setdefault(a, ds.id)
        for s in dv.samples:
            vocab.samples.setdefault(s, f"dataset:{ds.id}.sample_id")
    return vocab


def ref_failures_load(session: Session, project_ids: Any = None) -> dict[int, Any]:
    """QC flags and results through the fact port, one experiment at a time."""
    projects = eln.list_projects(session)
    wanted = set(project_ids) if project_ids is not None else {p.id for p in projects}
    items: dict[int, Any] = {}
    for p in projects:
        if p.id not in wanted:
            continue
        for e in eln.list_experiments_full(session, p.id):
            items[e.id] = failures._Exp(
                exp=e,
                project_name=p.name,
                flags=ports.qc_flags(session, e.id) or [],
                results=ports.results(session, e.id),
            )
    for item in items.values():
        pid = item.exp.parent_experiment_id
        if pid is not None and pid in items:
            item.parent = items[pid].exp
            items[pid].children.append(item.exp.id)
    return items


def _ref_descends(item: Any, ancestor_id: int, items: dict[int, Any]) -> bool:
    seen: set[int] = set()
    cur = item.exp.parent_experiment_id
    while cur is not None and cur not in seen and cur in items:
        if cur == ancestor_id:
            return True
        seen.add(cur)
        cur = items[cur].exp.parent_experiment_id
    return False


def _ref_same_base(earlier: Any, later: Any, items: dict[int, Any]) -> bool:
    same_parent = (
        earlier.exp.parent_experiment_id is not None
        and later.exp.parent_experiment_id == earlier.exp.parent_experiment_id
    )
    return same_parent or _ref_descends(later, earlier.exp.id, items)


def ref_links(failure_list: list[Any], items: dict[int, Any]) -> list[FailurePatternLink]:
    """Repeat links, walking the lineage chain for every (earlier, later) pair."""
    links: list[FailurePatternLink] = []
    by_id = {f.exp.id: f for f in failure_list}
    for later in failure_list:
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
    for i, earlier in enumerate(failure_list):
        introduced = [c for c in earlier.changes if c.change != "removed"]
        if not introduced:
            continue
        for later in failure_list[i + 1 :]:
            if later.exp.parent_experiment_id == earlier.exp.id:
                continue
            if not _ref_same_base(earlier, later, items):
                continue
            shared = sorted(set(earlier.failed_analytes) & set(later.failed_analytes))
            if not shared:
                continue
            cond = mem_conditions.conditions(later.exp)
            for c in introduced:
                if c.key in cond and cond[c.key] == c.value_b:
                    links.append(
                        FailurePatternLink(
                            kind="same_condition",
                            from_experiment_id=earlier.exp.id,
                            to_experiment_id=later.exp.id,
                            key=c.key,
                            label=mem_conditions.label(c.key),
                            value=c.value_b,
                            shared_analytes=shared,
                        )
                    )
                    break
    return links


FTS = search_index.FTS_TABLE
_REF_DDL = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS} USING fts5("
    "text, doc_key UNINDEXED, project_id UNINDEXED, experiment_id UNINDEXED, "
    "field UNINDEXED, ref_type UNINDEXED, ref_id UNINDEXED, ref_field UNINDEXED, "
    "tokenize='trigram')"
)


def ref_sync(session: Session, project_id: int) -> int:
    """Old incremental sync: per event ``DELETE … WHERE doc_key`` (a full FTS scan) + insert."""
    if not search_index.table_exists(session):
        session.execute(text(_REF_DDL))
        session.query(IndexState).filter(IndexState.name.like("search:%")).delete()
    name = f"search:{project_id}"
    session.execute(
        sqlite_insert(IndexState).values(name=name, last_event_id=0).on_conflict_do_nothing()
    )
    state = session.get(IndexState, name, populate_existing=True)
    assert state is not None
    events = search_index._events(session, project_id, state.last_event_id)
    for ev in events:
        doc_key = f"{ev.entity_type}:{ev.entity_id}"
        session.execute(text(f"DELETE FROM {FTS} WHERE doc_key = :k"), {"k": doc_key})
        for d in search_index.documents_for(
            session, ev.entity_type, ev.entity_id, project_id, ev.payload or {}
        ):
            session.execute(
                text(
                    f"INSERT INTO {FTS} (text, doc_key, project_id, experiment_id, field, "
                    "ref_type, ref_id, ref_field) VALUES (:text, :doc_key, :project_id, "
                    ":experiment_id, :field, :ref_type, :ref_id, :ref_field)"
                ),
                d.__dict__,
            )
    if events:
        state.last_event_id = events[-1].id
    session.flush()
    return len(events)


def ref_rebuild_index(session: Session) -> None:
    """Full FTS rebuild the old way (both tables dropped, then :func:`ref_sync`)."""
    session.execute(text(f"DROP TABLE IF EXISTS {FTS}"))
    session.execute(text(f"DROP TABLE IF EXISTS {search_index.ROWS_TABLE}"))
    for p in eln.list_projects(session):
        ref_sync(session, p.id)


#: The fixes of PERFORMANCE.md, in the order they are applied (tests/perf_stages.py).
FIXES = (
    "dataset_index",  # eln: index on eln_datasets.supersedes_dataset_id (DB-level, not here)
    "fts",  # memory: FTS rowid map + set-based sync with batched reads
    "eln_batch",  # eln: experiment listing in 4 queries instead of 3 per experiment
    "metrics",  # analysis: batched metrics from light result views (Records)
    "failures",  # memory+wiring: batched fact ports, ancestor sets (failure archive)
    "recall",  # memory: experiment vocabulary in two queries per project
    "kg",  # memory+wiring: knowledge-graph prefetch, result heads without outputs
    "similarity",  # memory: pruned + vectorised condition similarity, changed keys only
)


def install(monkeypatch: pytest.MonkeyPatch, revert: Iterable[str] = FIXES) -> None:
    """Swap the optimised functions of the fixes in ``revert`` for their references."""
    revert = set(revert)
    vocab = _ref_vocab_any_meta
    if "similarity" in revert:
        monkeypatch.setattr(memory, "similar_pairs", mem_conditions.similar_pairs_bruteforce)
        monkeypatch.setattr(
            knowledge_graph, "similar_pairs", mem_conditions.similar_pairs_bruteforce
        )
        monkeypatch.setattr(memory, "changed_keys", ref_changed_keys)
        monkeypatch.setattr(knowledge_graph, "changed_keys", ref_changed_keys)
        monkeypatch.setattr(
            memory,
            "changed_condition_keys",
            lambda ca, cb, *_: [
                k for k in sorted(set(ca) | set(cb)) if k not in ca or k not in cb or ca[k] != cb[k]
            ],
        )
    if "fts" in revert:
        monkeypatch.setattr(search_index, "sync", ref_sync)
        monkeypatch.setattr(search_index, "dataset_vocab", vocab)
    if "eln_batch" in revert:
        monkeypatch.setattr(eln, "list_experiments_full", ref_list_experiments_full)
    if "metrics" in revert:
        monkeypatch.setattr(analysis, "get_metrics", ref_get_metrics)
        monkeypatch.setattr(records, "_rows", ref_records_rows)
    if "failures" in revert:
        monkeypatch.setattr(failures, "load", ref_failures_load)
        monkeypatch.setattr(failures, "_links", ref_links)
    if "recall" in revert:
        monkeypatch.setattr(
            memory,
            "experiment_vocabs",
            lambda session, _pid, exps: {e.id: ref_experiment_vocab(session, e) for e in exps},
        )
    if "kg" in revert:
        monkeypatch.setattr(knowledge_graph._Builder, "prefetch", lambda self, events: None)
        monkeypatch.setattr(knowledge_graph, "dataset_vocab", vocab)
    if revert & {"failures", "kg"}:
        # Same name, same position in the registry: replaces the optimised provider.
        provider = RefAnalysisFactProvider(results="failures" in revert, describe="kg" in revert)
        monkeypatch.setitem(ports._providers, "analysis", provider)
