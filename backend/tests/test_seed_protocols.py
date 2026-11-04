"""Lab profile: the residue SOP history v1 → v1.1 → v1.2 → v2 as protocol templates.

Each residue experiment is recorded with the SOP version it was run under; the lineage
shows condition-level changes between versions, and Analysis groups the stored QC
outcomes per version. Values are checked against the seed spec, not hard-coded.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.analysis import records
from app.eln import service as eln
from app.seed.loader import SeedResult
from app.seed.spec import SeedSpec


def test_sop_versions_and_condition_changes(
    lab_session: Session, lab: SeedResult, lab_spec: SeedSpec
) -> None:
    lineage = eln.protocol_lineage(lab_session, lab.project_ids["residue"])
    assert len(lineage.lineages) == 1
    versions = lineage.lineages[0].versions
    assert [v.template.display_version for v in versions] == ["v1", "v1.1", "v1.2", "v2"]
    assert [v.template.source_experiment_code for v in versions] == [None, "#004", "#008", "#017"]
    changed = [{c.key for c in v.changes_from_previous} for v in versions]
    assert changed == [
        set(),
        {"cleanup_sorbent"},
        {"column_temp_c", "calibration_weighting"},
        {"sample_mass_g", "extraction_solvent", "extraction_volume_ml", "ph", "buffer"},
    ]
    residue = lab_spec.project("residue")
    for proto, node in zip(lab_spec.protocols, versions, strict=True):
        assert [u.code for u in node.experiments] == proto.experiments
        before = residue.experiment(proto.conditions_of).condition_block
        assert node.template.template_id and node.changes_from_previous is not None
        for use in node.experiments:
            exp = residue.experiment(use.code).condition_block
            expected = {k for k in {*before, *exp} if before.get(k) != exp.get(k)}
            assert {d.key for d in use.deviations} == expected
        dates = [residue.experiment(c).performed_on for c in proto.experiments]
        assert (node.first_used_on, node.last_used_on) == (min(dates), max(dates))
    # Every residue experiment is linked; organic acids have no protocol template.
    assert sum(len(v.experiments) for v in versions) == 30
    assert eln.protocol_lineage(lab_session, lab.project_ids["organic_acids"]).lineages == []


def test_sop_templates_have_executable_steps(lab_session: Session, lab: SeedResult) -> None:
    items = eln.list_protocol_templates(
        lab_session, lab.project_ids["residue"], all_versions=True
    ).items
    assert len(items) == 4
    for tpl in items:
        assert not tpl.steps_derived and len(tpl.steps) == 7
        named = {k for s in tpl.steps for k in s.condition_keys}
        assert named == set(tpl.condition_block.model_dump(exclude_none=True))


def test_qc_pass_rate_per_sop_version(lab_session: Session, lab: SeedResult) -> None:
    out = records.by_protocol(lab_session, [lab.project_ids["residue"]])
    lineage = eln.protocol_lineage(lab_session, lab.project_ids["residue"]).lineages[0]
    ids = {v.template.template_id: len(v.experiments) for v in lineage.versions}
    assert {g.value for g in out.groups} == set(ids)
    for g in out.groups:
        assert g.experiment_count == ids[g.value]
        assert g.pass_count + g.fail_count == g.analyzed_count
        assert g.pass_count == sum(
            1 for e in g.experiments if e.qc_status not in ("fail", "not_analyzed")
        )
    ratios = [g.pass_ratio for g in out.groups if g.pass_ratio is not None]
    assert ratios == sorted(ratios, reverse=True)
