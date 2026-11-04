"""Composition root: connects higher-layer services to Memory's fact ports.

Memory may only depend on ELN (CLAUDE.md §2), yet its diff, recall and knowledge
graph must show stored Analysis results and Partner records. Memory therefore
defines :class:`app.memory.schemas.FactProvider`; this module — which, like
``app/main.py`` and ``app/models_registry.py``, sits outside every feature module —
implements it on top of ``app.analysis.service`` / ``app.partner.service`` and
registers the providers. Providers only *read* stored records and copy values;
every number (incl. deltas and p-values) is the one Analysis already computed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.analysis.schemas import (
    AnalysisResultOut,
    ExperimentMetrics,
    ResultHead,
    ResultKind,
)
from app.core.errors import NotFoundError
from app.memory import service as memory
from app.memory.schemas import (
    EntityFacts,
    FactProvider,
    ProposalFact,
    QCFact,
    ResultDelta,
    ResultFact,
    SourceRef,
)
from app.partner import service as partner

RESULT_REF = "analysis.AnalysisResult"

_KIND_LABELS: dict[str, str] = {
    "calibration": "검량선",
    "recovery": "회수율",
    "is_response": "IS 응답",
    "matrix_effect": "매트릭스 효과",
}


def _src(result: AnalysisResultOut | None, field: str, experiment_id: int) -> list[SourceRef]:
    if result is None:
        return []
    return [
        SourceRef(ref_type=RESULT_REF, ref_id=result.id, field=field, experiment_id=experiment_id)
    ]


def _result_facts(
    experiment_id: int, m: ExperimentMetrics, result_ids: dict[ResultKind, int]
) -> list[ResultFact]:
    """Result facts of one experiment: its metrics, each sourced to the latest result id."""
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
        rid = result_ids.get(kind)
        if rid is None or value is None:
            return
        out.append(
            ResultFact(
                metric=metric,
                label=lbl,
                analyte=analyte,
                value=value,
                unit=unit,
                source=SourceRef(
                    ref_type=RESULT_REF, ref_id=rid, field=field, experiment_id=experiment_id
                ),
            )
        )

    add(
        "recovery",
        "recovery_mean_pct",
        "평균 회수율",
        m.recovery_mean_pct,
        "%",
        "output.overall_mean_pct",
    )
    add(
        "recovery",
        "recovery_rsd_pct",
        "회수율 RSD",
        m.recovery_rsd_pct,
        "%",
        "output.overall_rsd_pct",
    )
    for a in m.per_analyte_recovery:
        add(
            "recovery",
            "analyte_recovery_mean_pct",
            f"{a.analyte} 평균 회수율",
            a.mean_pct,
            "%",
            f"output.rows[analyte={a.analyte}].recovery_pct",
            a.analyte,
        )
    add(
        "calibration",
        "min_r_squared",
        "최소 R²",
        m.min_r_squared,
        None,
        "output.analytes[].r_squared",
    )
    if m.is_injections_flagged is not None:
        add(
            "is_response",
            "is_injections_flagged",
            "IS 이상 주입 수",
            float(m.is_injections_flagged),
            "회",
            "output.flagged_count",
        )
    for analyte, me in m.matrix_effect_pct.items():
        add(
            "matrix_effect",
            "matrix_effect_pct",
            f"{analyte} 매트릭스 효과",
            me,
            "%",
            f"output.analytes[analyte={analyte}].matrix_effect_pct",
            analyte,
        )
    return out


def _qc_facts(experiment_id: int, refs: dict[ResultKind, ResultHead]) -> list[QCFact]:
    """QC flags of the latest stored result of each kind, each with its source path."""
    out: list[QCFact] = []
    for res in refs.values():
        for i, f in enumerate(res.flags):
            out.append(
                QCFact(
                    code=f.code,
                    severity=f.severity,
                    analyte=f.analyte,
                    value=f.value,
                    context=f.context,
                    source=SourceRef(
                        ref_type=RESULT_REF,
                        ref_id=res.id,
                        field=f"flags[{i}]",
                        experiment_id=experiment_id,
                    ),
                )
            )
    return out


def _result_entity(res: ResultHead) -> EntityFacts:
    """Knowledge-graph label and flagged analytes of one stored result."""
    return EntityFacts(
        ref_type=RESULT_REF,
        ref_id=res.id,
        label=f"{_KIND_LABELS.get(res.kind, res.kind)} 결과 ({res.method_version})",
        experiment_id=res.experiment_id,
        kind=res.kind,
        flagged_analytes=sorted({f.analyte for f in res.flags if f.analyte}),
    )


class AnalysisFactProvider(FactProvider):
    """Stored analysis results, comparisons and QC flags (read-only)."""

    name = "analysis"

    def results(self, session: Session, experiment_id: int) -> list[ResultFact]:
        """Headline metrics of the latest stored results with their result ids."""
        m = analysis.get_metrics(session, experiment_id)
        ids = analysis.latest_result_ids_many(session, [experiment_id])[experiment_id]
        return _result_facts(experiment_id, m, ids)

    def results_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[ResultFact]]:
        """:meth:`results` of many experiments with batched reads (two queries per 500)."""
        metrics = analysis.get_metrics_many(session, experiment_ids)
        ids = analysis.latest_result_ids_many(session, experiment_ids)
        return {i: _result_facts(i, metrics[i], ids[i]) for i in experiment_ids}

    def result_deltas(self, session: Session, a_id: int, b_id: int) -> list[ResultDelta] | None:
        """Pairs of stored metrics; deltas/p-values exactly as ``analysis.compare`` returns."""
        cmp = analysis.compare(session, a_id, b_id)
        la, lb = analysis.latest_results(session, a_id), analysis.latest_results(session, b_id)
        ma, mb = cmp.metrics_a, cmp.metrics_b
        out: list[ResultDelta] = []

        def sources(kind: ResultKind, field: str) -> list[SourceRef]:
            return _src(la.get(kind), field, a_id) + _src(lb.get(kind), field, b_id)

        if ma.recovery_mean_pct is not None or mb.recovery_mean_pct is not None:
            out.append(
                ResultDelta(
                    metric="recovery_mean_pct",
                    label="평균 회수율",
                    unit="%",
                    value_a=ma.recovery_mean_pct,
                    value_b=mb.recovery_mean_pct,
                    delta=cmp.recovery_delta_pct_points,
                    p_value=cmp.recovery_t_test.p_value if cmp.recovery_t_test else None,
                    sources=sources("recovery", "output.overall_mean_pct"),
                )
            )
        for d in cmp.per_analyte:
            out.append(
                ResultDelta(
                    metric="analyte_recovery_mean_pct",
                    label=f"{d.analyte} 평균 회수율",
                    analyte=d.analyte,
                    unit="%",
                    value_a=d.mean_a_pct,
                    value_b=d.mean_b_pct,
                    delta=d.delta_pct_points,
                    sources=sources("recovery", f"output.rows[analyte={d.analyte}].recovery_pct"),
                )
            )
        pairs: list[tuple[ResultKind, str, str, Any, Any, str | None, str]] = [
            (
                "recovery",
                "recovery_rsd_pct",
                "회수율 RSD",
                ma.recovery_rsd_pct,
                mb.recovery_rsd_pct,
                "%",
                "output.overall_rsd_pct",
            ),
            (
                "calibration",
                "min_r_squared",
                "최소 R²",
                ma.min_r_squared,
                mb.min_r_squared,
                None,
                "output.analytes[].r_squared",
            ),
            (
                "is_response",
                "is_injections_flagged",
                "IS 이상 주입 수",
                ma.is_injections_flagged,
                mb.is_injections_flagged,
                "회",
                "output.flagged_count",
            ),
        ]
        for kind, metric, lbl, va, vb, unit, field in pairs:
            if va is None and vb is None:
                continue
            out.append(
                ResultDelta(
                    metric=metric,
                    label=lbl,
                    unit=unit,
                    value_a=None if va is None else float(va),
                    value_b=None if vb is None else float(vb),
                    sources=sources(kind, field),
                )
            )
        return out

    def qc_flags(self, session: Session, experiment_id: int) -> list[QCFact] | None:
        """QC flags of the latest stored result of each kind."""
        refs = analysis.latest_result_refs_many(session, [experiment_id])[experiment_id]
        return _qc_facts(experiment_id, refs)

    def qc_flags_many(
        self, session: Session, experiment_ids: list[int]
    ) -> dict[int, list[QCFact] | None]:
        """:meth:`qc_flags` of many experiments with one batched read."""
        refs = analysis.latest_result_refs_many(session, experiment_ids)
        return {i: _qc_facts(i, refs[i]) for i in experiment_ids}

    def describe(
        self,
        session: Session,
        ref_type: str,
        ref_id: int,
        project_id: int,
        payload: dict[str, Any],
    ) -> EntityFacts | None:
        """Label and flagged analytes of a stored analysis result."""
        return self.describe_many(session, ref_type, [(ref_id, payload)], project_id)[0]

    def describe_many(
        self,
        session: Session,
        ref_type: str,
        items: list[tuple[int, dict[str, Any]]],
        project_id: int,
    ) -> list[EntityFacts | None]:
        """:meth:`describe` of many results, read in one batch (outputs are not read)."""
        if ref_type != RESULT_REF:
            return [None] * len(items)
        heads = analysis.get_result_heads(session, sorted({i for i, _ in items}))
        return [_result_entity(heads[i]) if i in heads else None for i, _ in items]


class PartnerFactProvider(FactProvider):
    """Critiques, hypotheses, proposals and decisions (read-only)."""

    name = "partner"

    def describe(
        self,
        session: Session,
        ref_type: str,
        ref_id: int,
        project_id: int,
        payload: dict[str, Any],
    ) -> EntityFacts | None:
        """Labels and links of partner records."""
        try:
            if ref_type == "partner.Critique":
                c = partner.get_critique(session, ref_id)
                return EntityFacts(
                    ref_type=ref_type,
                    ref_id=ref_id,
                    label=f"비판 #{c.id} ({c.engine})",
                    experiment_id=c.experiment_id,
                    texts={"summary": c.summary},
                )
            if ref_type == "partner.Hypothesis":
                for h in partner.list_hypotheses(session, project_id):
                    if h.id == ref_id:
                        return EntityFacts(
                            ref_type=ref_type,
                            ref_id=ref_id,
                            label=h.statement,
                            experiment_id=h.experiment_id,
                            critique_id=h.critique_id,
                            status=h.status,
                            texts={"statement": h.statement},
                        )
                return None
            if ref_type == "partner.Proposal":
                p = partner.get_proposal(session, ref_id)
                return EntityFacts(
                    ref_type=ref_type,
                    ref_id=ref_id,
                    label=p.title,
                    experiment_id=p.experiment_id,
                    critique_id=p.critique_id,
                    hypothesis_id=p.hypothesis_id,
                    status=p.status,
                    texts={"title": p.title, "description": p.description},
                )
            if ref_type == "partner.Decision":
                proposal_id = payload.get("proposal_id")
                if proposal_id is None:
                    return None
                p = partner.get_proposal(session, int(proposal_id))
                if p.decision is None or p.decision.id != ref_id:
                    return None
                return EntityFacts(
                    ref_type=ref_type,
                    ref_id=ref_id,
                    label=f"{p.decision.action}: {p.decision.rationale}",
                    experiment_id=p.experiment_id,
                    proposal_id=p.id,
                    status=p.decision.action,
                    texts={"rationale": p.decision.rationale},
                )
        except NotFoundError:
            return None
        return None

    def proposals(self, session: Session, project_id: int) -> list[ProposalFact]:
        """Proposals with the changes a follow-up implements (Partner's
        ``implementing_changes``: a modify decision's modifications, design descriptors
        and to-be-chosen values removed), status and decision day."""
        out: list[ProposalFact] = []
        for p in partner.list_proposals(session, project_id):
            out.append(
                ProposalFact(
                    id=p.id,
                    experiment_id=p.experiment_id,
                    created_at=p.created_at,
                    changes={c.key: c.value for c in p.implementing_changes},
                    status=p.status,
                    decided_on=p.decision.decided_on if p.decision else None,
                )
            )
        return out


def install() -> None:
    """Register every fact provider with Memory and its write-time index sync (idempotent)."""
    memory.register_fact_provider(AnalysisFactProvider())
    memory.register_fact_provider(PartnerFactProvider())
    memory.install_search_index_sync()
