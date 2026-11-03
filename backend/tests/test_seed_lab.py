"""The ``lab`` seed profile: six months of a two-project lab.

Checks, in order:

1. shape — 2 projects, 42 experiments;
2. every number on screen is computed from the committed CSVs (independent re-fit);
3. the research graph of each project is one connected lineage tree;
4. the decision history: each decision is recorded right after its critique on the
   proposal named by the Partner's stable ids (template id + signature), later
   critiques never re-offer a decided proposal, follow-ups implement the decisions and
   rejected condition values are never used afterwards;
5. the scenario (protocol history, maintenance stop, failed reproduction, operator
   habits, cross-project links) is visible in the computed numbers — as ranges
   (CLAUDE.md §6), never as exact values.
"""

from __future__ import annotations

import hashlib
import io
import math
import statistics
from datetime import date, datetime

import networkx as nx
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.analysis.models import AnalysisResult
from app.analysis.schemas import (
    CalibrationOutput,
    ExperimentMetrics,
    MatrixEffectOutput,
    RecoveryOutput,
)
from app.core.audit import AuditEvent
from app.core.llm import RulesOnlyGateway
from app.eln import service as eln
from app.eln.models import Dataset, Experiment
from app.eln.schemas import ExperimentOut
from app.memory import service as memory
from app.memory.models import ExperimentDigest
from app.partner import service as partner
from app.partner.models import Critique, Decision, Hypothesis, Proposal
from app.partner.schemas import ExperimentDesign, ProposalChange, ProposalOut
from app.seed.loader import SeedError, SeedResult, find_decided_proposal
from app.seed.spec import REJECT_REASON_LABELS, DecisionSpec, SeedSpec

STATUS = {"accept": "accepted", "modify": "modified", "reject": "rejected"}
IS_PROPOSAL_KEYS = {"injection_dilution", "calibration_type"}


def _exp(s: Session, lab: SeedResult, project: str, code: str) -> ExperimentOut:
    return eln.get_experiment(s, lab.experiment_ids[(project, code)])


def _metrics(s: Session, lab: SeedResult, project: str, code: str) -> ExperimentMetrics:
    return analysis.get_metrics(s, lab.experiment_ids[(project, code)])


def _per_analyte(s: Session, lab: SeedResult, project: str, code: str) -> dict[str, float]:
    m = _metrics(s, lab, project, code)
    return {a.analyte: a.mean_pct for a in m.per_analyte_recovery}


def _proposal(s: Session, lab: SeedResult, d: DecisionSpec) -> ProposalOut:
    return partner.get_proposal(s, lab.decided_proposal_ids[d.id])


def _same_value(a: object, b: object) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b))
    return a == b


# ------------------------------------------------------------------ 1. shape


def test_lab_loads_two_projects_and_42_experiments(lab_session: Session, lab: SeedResult) -> None:
    projects = eln.list_projects(lab_session)
    assert len(projects) == 2
    counts = {p.id: p.experiment_count for p in projects}
    assert counts[lab.project_ids["residue"]] == 30
    assert counts[lab.project_ids["organic_acids"]] == 12
    assert sum(counts.values()) == 42 == len(lab.experiment_ids)
    codes = [e.code for e in eln.list_experiments(lab_session, lab.project_ids["residue"])]
    assert codes == [f"#{n:03d}" for n in range(1, 31)]


# -------------------------------------------- 2. numbers come from the CSV files


def test_stored_datasets_are_the_committed_csvs(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    for project in lab_spec.projects:
        for exp in project.experiments:
            stored = eln.list_datasets(lab_session, lab.experiment_ids[(project.key, exp.code)])
            assert [(d.kind, d.filename) for d in stored] == [
                (d.kind, d.file) for d in exp.datasets
            ]
            for ds, spec_ds in zip(stored, exp.datasets, strict=True):
                text = project.csv_path(spec_ds).read_text(encoding="utf-8")
                assert eln.get_dataset_content(lab_session, ds.id) == text
                assert ds.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_every_experiment_has_numbers_computed_from_its_csvs(
    lab_session: Session, lab: SeedResult
) -> None:
    for (project, code), exp_id in lab.experiment_ids.items():
        metrics = analysis.get_metrics(lab_session, exp_id)
        assert metrics.analyzed, f"{project} {code} has no analysis result"
        dataset_ids = {d.id for d in eln.list_datasets(lab_session, exp_id)}
        results = analysis.list_results(lab_session, exp_id)
        assert results
        for r in results:
            assert set(r.input_dataset_ids) <= dataset_ids, (code, r.kind)
        values = [
            metrics.recovery_mean_pct,
            metrics.recovery_rsd_pct,
            metrics.min_r_squared,
            *metrics.matrix_effect_pct.values(),
        ]
        assert all(math.isfinite(v) for v in values if v is not None), code
        rerun = analysis.run_experiment(lab_session, exp_id)
        assert rerun.created == 0 and rerun.skipped == [], code  # same CSV → same result


def _weights(x: np.ndarray, weighting: str) -> np.ndarray:
    return {"none": np.ones_like(x), "1/x": 1 / x, "1/x2": 1 / x**2}[weighting]


def test_numbers_recompute_independently_from_csv(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """Re-fit every calibration/recovery/ME with plain numpy from the CSV files."""
    for project in lab_spec.projects:
        for exp in project.experiments:
            exp_id = lab.experiment_ids[(project.key, exp.code)]
            latest = analysis.latest_results(lab_session, exp_id)
            frames = {
                d.kind: pd.read_csv(io.StringIO(project.csv_path(d).read_text("utf-8")))
                for d in exp.datasets
            }
            fits: dict[str, tuple[float, float]] = {}
            if "calibration" in frames:
                cal = frames["calibration"]
                out = latest["calibration"].output
                assert isinstance(out, CalibrationOutput)
                weighting = exp.condition_block.get("calibration_weighting", "none")
                for a in out.analytes:
                    g = cal[cal["analyte"] == a.analyte]
                    x = g["level_ng_ml"].to_numpy(float)
                    y = (g["analyte_area"] / g["is_area"]).to_numpy(float)
                    slope, intercept = np.polyfit(x, y, 1, w=np.sqrt(_weights(x, weighting)))
                    assert math.isclose(a.slope, slope, rel_tol=1e-8), (exp.code, a.analyte)
                    assert math.isclose(a.intercept, intercept, rel_tol=1e-6, abs_tol=1e-12)
                    fits[a.analyte] = (slope, intercept)
            if "recovery" in frames:
                rec = frames["recovery"]
                out = latest["recovery"].output
                assert isinstance(out, RecoveryOutput)
                cond = exp.condition_block
                factor = cond["extraction_volume_ml"] / cond["sample_mass_g"]
                slope_v = rec["analyte"].map({a: f[0] for a, f in fits.items()})
                inter_v = rec["analyte"].map({a: f[1] for a, f in fits.items()})
                conc = (rec["analyte_area"] / rec["is_area"] - inter_v) / slope_v * factor
                recovery = conc / rec["spike_ng_g"] * 100
                assert out.n == len(rec)
                assert math.isclose(out.overall_mean_pct, float(recovery.mean()), rel_tol=1e-9)
            if "matrix_effect" in frames:
                me = frames["matrix_effect"]
                out = latest["matrix_effect"].output
                assert isinstance(out, MatrixEffectOutput)
                for a in out.analytes:
                    g = me[me["analyte"] == a.analyte]
                    slopes = {
                        c: np.polyfit(part["level_ng_ml"], part["analyte_area"], 1)[0]
                        for c, part in g.groupby("curve")
                    }
                    expected = (slopes["matrix"] / slopes["solvent"] - 1) * 100
                    assert math.isclose(a.matrix_effect_pct, expected, rel_tol=1e-8)


# ------------------------------------------------------- 3. connected research graph


def test_research_graphs_have_no_disconnected_nodes(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    for project in lab_spec.projects:
        g = memory.get_graph(lab_session, lab.project_ids[project.key])
        root_id = lab.experiment_ids[(project.key, project.experiments[0].code)]
        assert g.roots == [root_id]
        assert len(g.nodes) == len(project.experiments)
        assert len(g.edges) == len(g.nodes) - 1  # a tree: every non-root has one parent
        graph = nx.DiGraph([(e.source, e.target) for e in g.edges])
        graph.add_nodes_from(n.id for n in g.nodes)
        assert nx.is_weakly_connected(graph)
        assert set(nx.descendants(graph, root_id)) | {root_id} == {n.id for n in g.nodes}
        dates = {n.id: n.performed_on for n in g.nodes}
        for edge in g.edges:
            assert dates[edge.source] <= dates[edge.target]
        for node in g.nodes:  # every lineage walks back to the project root
            assert memory.get_lineage(lab_session, node.id)[0].id == root_id


def test_lineage_restarts_nowhere(lab_session: Session, lab: SeedResult) -> None:
    """#018 (the reference baseline) hangs under the SOP v2 switch, not as a second root."""
    lineage = memory.get_lineage(lab_session, lab.experiment_ids[("residue", "#024")])
    codes = [e.code for e in lineage]
    assert codes[0] == "#001"
    assert codes[-3:] == ["#017", "#018", "#024"]


# --------------------------------------------------------------- 4. decisions


def _audit_id(s: Session, entity_type: str, entity_id: int) -> int:
    """Id of the creation audit event of a record (audit ids are the global write order)."""
    return min(
        s.scalars(
            select(AuditEvent.id).where(
                AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id
            )
        )
    )


def test_decisions_are_linked_to_the_right_proposals(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    decisions = lab_spec.history.decisions
    assert len(decisions) == len(lab.decided_proposal_ids) == 14
    for d in decisions:
        p = _proposal(lab_session, lab, d)
        exp_id = lab.experiment_ids[(d.project, d.experiment)]
        critique = partner.get_critique(lab_session, lab.critique_ids[d.critique])
        assert p.project_id == lab.project_ids[d.project]
        assert p.experiment_id == exp_id == critique.experiment_id
        assert p.id in critique.proposal_ids  # offered by the critique the spec names
        # matched by the Partner's stable ids; the readable copy in the spec agrees
        assert p.design is not None and p.design.template_id == d.proposal.template_id
        assert p.signature == d.proposal.signature
        assert [c.key for c in p.changes] == [c.key for c in d.proposal.changes]
        for got, want in zip(p.changes, d.proposal.changes, strict=True):
            assert _same_value(got.value, want.value), (d.id, got.key)
        assert p.status == STATUS[d.action]
        assert p.decision is not None
        assert p.decision.action == d.action
        assert p.decision.rationale == d.stored_rationale()
        assert p.decision.decided_by == d.decided_by
        authors = {e.author for e in eln.list_experiments(lab_session, p.project_id)}
        assert d.decided_by in authors
        if d.action == "modify":
            assert p.decision.modifications == d.modifications
        event = lab_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "partner.Decision",
                AuditEvent.entity_id == p.decision.id,
            )
        ).one()
        assert event.payload["proposal_id"] == p.id
    # Only the scenario's decisions exist; whatever else the Partner proposed stays
    # pending (the seed does not depend on the full set of engine proposals).
    decided = {
        p.id
        for project_id in lab.project_ids.values()
        for p in partner.list_proposals(lab_session, project_id)
        if p.status != "pending"
    }
    assert decided == set(lab.decided_proposal_ids.values())


def test_decisions_are_recorded_right_after_their_critique(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """Each decision lies between its critique and the project's next critique."""
    history = lab_spec.history
    for d in history.decisions:
        p = _proposal(lab_session, lab, d)
        assert p.decision is not None
        decided_at = _audit_id(lab_session, "partner.Decision", p.decision.id)
        own = _audit_id(lab_session, "partner.Critique", lab.critique_ids[d.critique])
        assert own < decided_at, d.id
        order = [c.id for c in history.critiques if c.project == d.project]
        later = order[order.index(d.critique) + 1 :]
        for c in later:
            assert decided_at < _audit_id(lab_session, "partner.Critique", lab.critique_ids[c])


def test_decisions_are_seed_actions_dated_on_their_experiment(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """ISSUES P1-9: the 14 back-filled decisions are seed records with their own day.

    Not ``actor="user"`` on the day the seed ran: the audit actor is ``seed`` like every
    other seeded record, and ``decided_on`` is the decided experiment's date (before
    its follow-up experiment).
    """
    for d in lab_spec.history.decisions:
        p = _proposal(lab_session, lab, d)
        assert p.decision is not None
        performed = _exp(lab_session, lab, d.project, d.experiment).performed_on
        assert p.decision.decided_on == performed, d.id
        if d.followed_by:
            follow = _exp(lab_session, lab, d.project, d.followed_by)
            assert p.decision.decided_on < follow.performed_on, d.id
        events = lab_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "partner.Decision",
                AuditEvent.entity_id == p.decision.id,
            )
        ).all()
        assert [(e.actor, e.payload["decided_by"]) for e in events] == [("seed", d.decided_by)]
        assert events[0].payload["decided_on"] == performed.isoformat()


def test_later_critiques_never_reoffer_a_decided_proposal(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """The stored history itself honours the decisions taken before each critique."""
    history = lab_spec.history
    for d in history.decisions:
        decided = _proposal(lab_session, lab, d)
        order = [c.id for c in history.critiques if c.project == d.project]
        for c in order[order.index(d.critique) + 1 :]:
            critique = partner.get_critique(lab_session, lab.critique_ids[c])
            offered = [partner.get_proposal(lab_session, pid) for pid in critique.proposal_ids]
            assert all(o.signature != decided.signature for o in offered), (d.id, c)


def test_recritiques_offer_what_the_first_critique_did_not(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """A second critique of an experiment exists because the decisions changed its offer."""
    history = lab_spec.history
    seen: dict[tuple[str, str], list[str]] = {}
    for c in history.critiques:
        seen.setdefault((c.project, c.experiment), []).append(c.id)
    recritiques = {key: ids for key, ids in seen.items() if len(ids) > 1}
    assert set(recritiques) == {("residue", "#009"), ("organic_acids", "#OA06")}
    for first, *again in recritiques.values():
        before = partner.get_critique(lab_session, lab.critique_ids[first]).proposal_ids
        assert history.decisions_after(first), "a re-critique follows a decision"
        for critique_id in again:
            for d in history.decisions_after(critique_id):
                assert lab.decided_proposal_ids[d.id] not in before, d.id


def test_rejections_carry_their_reason(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    rejects = [d for d in lab_spec.history.decisions if d.action == "reject"]
    assert len(rejects) == 7
    assert {d.reason for d in rejects} == set(REJECT_REASON_LABELS)
    for d in rejects:
        p = _proposal(lab_session, lab, d)
        assert p.status == "rejected" and p.decision is not None
        assert d.reason is not None
        assert p.decision.rationale.startswith(f"[{REJECT_REASON_LABELS[d.reason]}] ")
    stored = partner.list_proposals(lab_session, lab.project_ids["residue"], status="rejected")
    stored += partner.list_proposals(
        lab_session, lab.project_ids["organic_acids"], status="rejected"
    )
    assert {p.id for p in stored} == {lab.decided_proposal_ids[d.id] for d in rejects}


def test_follow_up_experiments_implement_the_decision(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    followed = [d for d in lab_spec.history.decisions if d.followed_by]
    assert len(followed) == 7
    for d in followed:
        assert d.followed_by is not None
        p = _proposal(lab_session, lab, d)
        decided = _exp(lab_session, lab, d.project, d.experiment)
        follow = _exp(lab_session, lab, d.project, d.followed_by)
        assert follow.performed_on > decided.performed_on
        assert d.experiment in follow.raw_note  # the note cites where the idea came from
        applied: list[ProposalChange] = d.modifications if d.action == "modify" else p.changes
        conditions = follow.condition_block.model_dump()
        for change in applied:
            assert _same_value(conditions.get(change.key), change.value), (d.id, change.key)
        # Partner names the same changes as what a follow-up implements (ISSUES P1-10)
        assert [(c.key, c.value) for c in p.implementing_changes] == [
            (c.key, c.value) for c in applied if c.value != "researcher-defined"
        ], d.id


def _project_condition_keys(s: Session, project_id: int) -> set[str]:
    return {
        key
        for e in eln.list_experiments_full(s, project_id)
        for key in e.condition_block.model_dump(exclude_none=True)
    }


def test_rejected_condition_values_are_never_used_later(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """A rejected condition value (e.g. methanol) never shows up in a later experiment.

    Only changes to keys the project actually records in its condition blocks are
    checked, and each value must be the one recorded on the decided experiment — so
    the check compares real condition values, not proposal placeholders such as
    ``researcher-defined``. Rejections of a whole design (2×2, re-analysis) reject the
    work, not a value; the no-repeat tests cover those.
    """
    rejects = [d for d in lab_spec.history.decisions if d.action == "reject"]
    single = {d.id for d in rejects if d.proposal.template_id == "single_variable"}
    checked: set[str] = set()
    for d in rejects:
        p = _proposal(lab_session, lab, d)
        project_id = lab.project_ids[d.project]
        keys = _project_condition_keys(lab_session, project_id)
        concrete = [c for c in p.changes if c.key in keys]
        if not concrete:
            continue
        checked.add(d.id)
        decided = _exp(lab_session, lab, d.project, d.experiment)
        recorded = decided.condition_block.model_dump()
        later = [
            e
            for e in eln.list_experiments_full(lab_session, project_id)
            if e.performed_on > decided.performed_on
        ]
        assert later
        for change in concrete:
            assert _same_value(recorded.get(change.key), change.value), (d.id, change.key)
            for e in later:
                used = e.condition_block.model_dump().get(change.key)
                assert not _same_value(used, change.value), (d.id, e.code, change.key)
    assert checked == single and len(checked) == 3


def _varied(p: ProposalOut) -> dict[str, list[object]]:
    assert p.design is not None
    return {v.key: list(v.levels) for v in p.design.variables if v.role == "varied"}


def test_repeat_probes_still_meet_the_rejected_proposals_trigger(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    """Each probe still shows the data situation that prompted the rejected proposal.

    The trigger is read from the stored data, not from the engine: an IS re-analysis
    needs flagged IS injections; a design that varies condition keys needs a
    confounded change of exactly those keys (to one of the design's levels) and a drop
    in recovery against the parent experiment.
    """
    by_id = {d.id: d for d in lab_spec.history.decisions}
    probes = lab_spec.history.repeat_probes
    assert {p.decision for p in probes} == {d.id for d in by_id.values() if d.action == "reject"}
    for probe in probes:
        rejected = _proposal(lab_session, lab, by_id[probe.decision])
        exp = _exp(lab_session, lab, probe.project, probe.experiment)
        keys = _project_condition_keys(lab_session, lab.project_ids[probe.project])
        varied = {k: levels for k, levels in _varied(rejected).items() if k in keys}
        if not varied:  # IS re-analysis (injection dilution is not a recorded condition)
            assert {c.key for c in rejected.changes} & IS_PROPOSAL_KEYS, probe
            assert (analysis.get_metrics(lab_session, exp.id).is_injections_flagged or 0) > 0
            continue
        assert exp.parent_experiment_id is not None
        diff = memory.diff(lab_session, exp.parent_experiment_id, exp.id)
        changed = {c.key: c.value_b for c in diff.condition_changes}
        assert len(changed) > 1  # confounded design → 2×2 / single-variable proposals
        for key, levels in varied.items():
            assert key in changed, (probe, key)
            assert any(_same_value(changed[key], level) for level in levels), (probe, key)
        delta = analysis.compare(lab_session, exp.parent_experiment_id, exp.id)
        assert delta.recovery_delta_pct_points is not None
        assert delta.recovery_delta_pct_points < 0


def _signature(p: ProposalOut) -> frozenset[tuple[str, str]]:
    """Engine-independent content fingerprint (numbers normalised: 10 == 10.0)."""

    def norm(v: object) -> str:
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v)

    return frozenset((c.key, norm(c.value)) for c in p.changes)


def test_critic_does_not_repeat_rejected_proposals(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    by_id = {d.id: d for d in lab_spec.history.decisions}
    for probe in lab_spec.history.repeat_probes:
        rejected = _proposal(lab_session, lab, by_id[probe.decision])
        crit = partner.run_critique(
            lab_session,
            lab.experiment_ids[(probe.project, probe.experiment)],
            gateway=RulesOnlyGateway(),
        )
        new = [partner.get_proposal(lab_session, pid) for pid in crit.proposal_ids]
        assert all(_signature(p) != _signature(rejected) for p in new), probe
        assert all(p.signature != rejected.signature for p in new), probe


def _offered(template_id: str, signature: str, pid: int = 1) -> ProposalOut:
    return ProposalOut(
        id=pid,
        project_id=1,
        experiment_id=1,
        critique_id=1,
        hypothesis_id=None,
        title="t",
        description="d",
        changes=[ProposalChange(key="ph", value=5)],
        evidence_keys=[],
        status="pending",
        origin="ai:rules",
        decision=None,
        design=ExperimentDesign(template_id=template_id, objective="o"),
        signature=signature,
        created_at=datetime(2026, 1, 1),
    )


def test_decided_proposal_is_never_guessed(lab_spec: SeedSpec) -> None:
    """Missing template/signature → SeedError that lists what the critique offered."""
    d = lab_spec.history.decisions[0]
    ref = d.proposal
    hit = _offered(ref.template_id, ref.signature, pid=7)
    assert find_decided_proposal([_offered("other", ref.signature), hit], d) is hit
    same_keys_other_signature = _offered(ref.template_id, "0" * 64)
    with pytest.raises(SeedError, match=r"offered 0 proposals[\s\S]*P1 template="):
        find_decided_proposal([same_keys_other_signature], d)
    with pytest.raises(SeedError, match="no proposals"):
        find_decided_proposal([], d)


# ----------------------------------------------------------- 5. the scenario


def test_protocol_change_history(lab_session: Session, lab: SeedResult) -> None:
    v1 = _metrics(lab_session, lab, "residue", "#001")
    assert v1.calibration_weighting == "none"
    assert any(f.code == "calibration_back_calc_error" for f in v1.flags)  # unweighted fit
    assert _metrics(lab_session, lab, "residue", "#007").calibration_weighting == "1/x"
    sop_v2 = _exp(lab_session, lab, "residue", "#017")
    baseline = _exp(lab_session, lab, "residue", "#018")
    assert sop_v2.condition_block == baseline.condition_block
    switch = memory.diff(lab_session, sop_v2.parent_experiment_id or 0, sop_v2.id)
    assert {c.key for c in switch.condition_changes} >= {"buffer", "sample_mass_g", "ph"}
    for code in ("#017", "#018"):
        mean = _metrics(lab_session, lab, "residue", code).recovery_mean_pct
        assert mean is not None and 85 <= mean <= 95
    timeline = memory.get_timeline(lab_session, lab.project_ids["residue"])
    changed = [t.code for t in timeline if "calibration_weighting" in t.changed_keys_vs_parent]
    assert changed == ["#007"]


def test_instrument_maintenance_stops_both_projects(lab_session: Session, lab: SeedResult) -> None:
    stop, restart = date(2026, 7, 13), date(2026, 8, 3)
    for project_id in lab.project_ids.values():
        dates = [e.performed_on for e in eln.list_experiments(lab_session, project_id)]
        assert not [d for d in dates if stop <= d <= restart]
        assert any(d < stop for d in dates) and any(d > restart for d in dates)
    before = _metrics(lab_session, lab, "residue", "#011")
    aborted = _metrics(lab_session, lab, "residue", "#012")
    assert (before.is_injections_flagged or 0) >= 1
    assert (aborted.is_injections_flagged or 0) >= 2
    assert aborted.is_injections_total == 6  # 10 planned, aborted after S-06
    same_week = _metrics(lab_session, lab, "organic_acids", "#OA03")
    assert (same_week.is_injections_flagged or 0) >= 1
    after = _metrics(lab_session, lab, "residue", "#013")
    assert after.recovery_mean_pct is None and after.min_r_squared is not None


def test_failed_reproduction_and_retry(lab_session: Session, lab: SeedResult) -> None:
    target = _metrics(lab_session, lab, "residue", "#010").recovery_mean_pct
    fail = _metrics(lab_session, lab, "residue", "#014")
    retry = _metrics(lab_session, lab, "residue", "#015").recovery_mean_pct
    fixed = _metrics(lab_session, lab, "residue", "#016").recovery_mean_pct
    assert target is not None and fail.recovery_mean_pct is not None
    assert retry is not None and fixed is not None
    assert target >= 85 and fail.recovery_mean_pct <= 78 and retry <= 80 and fixed >= 82
    assert any(f.code == "recovery_out_of_range" for f in fail.flags)
    # the cause is not in the condition block: #014 repeats #010 exactly (reagent lot)
    e010, e014 = (_exp(lab_session, lab, "residue", c) for c in ("#010", "#014"))
    assert memory.diff(lab_session, e010.id, e014.id).condition_changes == []
    assert "MgSO4" in e014.raw_note
    retry_id = lab.experiment_ids[("residue", "#016")]
    lineage = [e.code for e in memory.get_lineage(lab_session, retry_id)]
    assert lineage[-4:] == ["#010", "#014", "#015", "#016"]


def _group_rsds(s: Session, exp_ids: list[int]) -> list[float]:
    rsds: list[float] = []
    for exp_id in exp_ids:
        rec = analysis.latest_results(s, exp_id).get("recovery")
        if rec is not None and isinstance(rec.output, RecoveryOutput):
            rsds += [g.rsd_pct for g in rec.output.groups if g.n >= 3]
    return rsds


def test_operator_habits_leave_a_trace(lab_session: Session, lab: SeedResult) -> None:
    kim, lee = (_exp(lab_session, lab, "residue", c) for c in ("#029", "#030"))
    assert {kim.author, lee.author} == {"김연구", "이분석"}
    assert memory.diff(lab_session, kim.id, lee.id).condition_changes == []  # same SOP
    cmp = analysis.compare(lab_session, kim.id, lee.id)
    assert cmp.recovery_t_test is not None and cmp.recovery_t_test.p_value < 0.05
    assert cmp.recovery_delta_pct_points is not None and cmp.recovery_delta_pct_points > 3
    assert cmp.metrics_b.recovery_rsd_pct is not None and cmp.metrics_a.recovery_rsd_pct is not None
    assert cmp.metrics_b.recovery_rsd_pct < cmp.metrics_a.recovery_rsd_pct
    for project_id in lab.project_ids.values():  # same pattern across the whole lab
        by_author: dict[str, list[int]] = {}
        for e in eln.list_experiments(lab_session, project_id):
            by_author.setdefault(e.author, []).append(e.id)
        kim_rsd = statistics.median(_group_rsds(lab_session, by_author["김연구"]))
        lee_rsd = statistics.median(_group_rsds(lab_session, by_author["이분석"]))
        assert kim_rsd > lee_rsd


def test_gcb_follow_up_separates_adsorption_from_suppression(
    lab_session: Session, lab: SeedResult
) -> None:
    planar = {"carbendazim", "thiabendazole"}
    gcb = _per_analyte(lab_session, lab, "residue", "#026")
    assert all(gcb[a] < 70 for a in planar)
    assert all(v >= 70 for a, v in gcb.items() if a not in planar)
    assert all(v >= 70 for v in _per_analyte(lab_session, lab, "residue", "#027").values())
    time_only = _metrics(lab_session, lab, "residue", "#025").recovery_mean_pct
    assert time_only is not None and 82 <= time_only <= 95
    original = _metrics(lab_session, lab, "residue", "#024")
    small_injection = _metrics(lab_session, lab, "residue", "#028")
    assert (original.is_injections_flagged or 0) >= 2
    assert small_injection.is_injections_flagged == 0
    assert all(_per_analyte(lab_session, lab, "residue", "#028")[a] < 70 for a in planar)


def test_organic_acid_story(lab_session: Session, lab: SeedResult) -> None:
    def mean(code: str) -> float:
        value = _metrics(lab_session, lab, "organic_acids", code).recovery_mean_pct
        assert value is not None
        return value

    assert mean("#OA06") < 50  # PSA (from the residue SOP) removes organic acids
    assert mean("#OA07") >= 80  # the solvent alone was not the problem
    assert mean("#OA04") > mean("#OA01")  # HSS T3 retains citric/malic acid
    assert mean("#OA08") > mean("#OA04")  # 13C IS tracks ESI− suppression
    assert mean("#OA11") > mean("#OA10")  # methanol, not extraction time, lowered #OA10
    me_c18 = _metrics(lab_session, lab, "organic_acids", "#OA02").matrix_effect_pct
    me_t3 = _metrics(lab_session, lab, "organic_acids", "#OA05").matrix_effect_pct
    assert me_c18["citric acid"] < -30
    assert all(abs(v) < abs(me_c18[a]) for a, v in me_t3.items())


def test_projects_share_instrument_is_and_people(lab_session: Session, lab: SeedResult) -> None:
    exps = {
        key: eln.list_experiments_full(lab_session, pid) for key, pid in lab.project_ids.items()
    }
    residue, acids = exps["residue"], exps["organic_acids"]
    assert {e.author for e in residue} == {e.author for e in acids} == {"김연구", "이분석"}
    for e in residue + acids:
        assert "LC-MS/MS" in (e.condition_block.instrument or "")
    shared_is = {e.condition_block.internal_standard for e in residue} & {
        e.condition_block.internal_standard for e in acids
    }
    assert shared_is == {"TPP (triphenyl phosphate)"}
    shared_column = {e.condition_block.column for e in residue} & {
        e.condition_block.column for e in acids
    }
    assert shared_column == {"C18 2.1×100 mm, 1.8 µm"}
    acid_codes, residue_codes = {e.code for e in acids}, {e.code for e in residue}
    assert any(c in e.raw_note for e in residue for c in acid_codes)
    assert any(c in e.raw_note for e in acids for c in residue_codes)
    for project_id in lab.project_ids.values():
        assert memory.search(lab_session, project_id, "TPP")


# ------------------------------------------------------------- principles


def test_every_lab_record_is_audited(lab_session: Session) -> None:
    expected = {
        "eln.Experiment": Experiment,
        "eln.Dataset": Dataset,
        "analysis.AnalysisResult": AnalysisResult,
        "memory.ExperimentDigest": ExperimentDigest,
        "partner.Critique": Critique,
        "partner.Hypothesis": Hypothesis,
        "partner.Proposal": Proposal,
        "partner.Decision": Decision,
    }
    for entity_type, model in expected.items():
        ids = set(lab_session.scalars(select(model.id)))
        audited = set(
            lab_session.scalars(
                select(AuditEvent.entity_id).where(AuditEvent.entity_type == entity_type)
            )
        )
        assert ids and ids <= audited, entity_type


def test_lab_originals_match_the_scenario_files(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    for project in lab_spec.projects:
        for spec_exp in project.experiments:
            exp = _exp(lab_session, lab, project.key, spec_exp.code)
            assert exp.raw_note == spec_exp.raw_note
            assert exp.condition_block.model_dump(exclude_none=True) == {
                k: v for k, v in spec_exp.condition_block.items()
            }
            assert exp.author == spec_exp.author and exp.performed_on == spec_exp.performed_on
