"""Deterministic diff engine: conditions, results, QC — every item with sources."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.memory import service
from app.memory.schemas import QCFact, SourceRef
from app.memory.textdiff import note_diff, tokenize, word_segments


def test_018_vs_024_conditions_results_and_qc_with_sources(
    session: Session, seeded: dict[str, int]
) -> None:
    a, b = seeded["#018"], seeded["#024"]
    d = service.diff(session, a, b)

    # conditions: exactly the two protocol changes, each traced to both experiments
    changes = {c.key: c for c in d.condition_changes}
    assert set(changes) == {"extraction_time_min", "cleanup_sorbent"}
    assert (changes["extraction_time_min"].value_a, changes["extraction_time_min"].value_b) == (
        10.0,
        5.0,
    )
    assert "GCB" in str(changes["cleanup_sorbent"].value_b)
    for c in changes.values():
        assert {(s.ref_type, s.ref_id, s.field) for s in c.sources} == {
            ("eln.Experiment", a, f"condition_block.{c.key}"),
            ("eln.Experiment", b, f"condition_block.{c.key}"),
        }

    # results: recovery difference from stored Analysis results
    assert d.results_available
    results = {(r.metric, r.analyte): r for r in d.result_changes}
    rec = results[("recovery_mean_pct", None)]
    assert rec.value_a is not None and 85 <= rec.value_a <= 93
    assert rec.value_b is not None and 58 <= rec.value_b <= 66
    assert rec.delta is not None and -35 <= rec.delta <= -20
    assert rec.p_value is not None and rec.p_value < 0.05
    assert {s.experiment_id for s in rec.sources} == {a, b}
    assert all(
        s.ref_type == "analysis.AnalysisResult" and s.field == "output.overall_mean_pct"
        for s in rec.sources
    )
    carb = results[("analyte_recovery_mean_pct", "carbendazim")]
    assert carb.delta is not None and carb.delta < -20
    assert results[("is_injections_flagged", None)].value_b == 3

    # QC: carbendazim/thiabendazole out of range and 3 IS suppressions appear in #024
    appeared = [q for q in d.qc_changes if q.change == "appeared"]
    out_of_range = {q.analyte for q in appeared if q.code == "recovery_out_of_range"}
    assert {"carbendazim", "thiabendazole"} <= out_of_range
    assert len([q for q in appeared if q.code == "is_suppression"]) == 3
    assert all(q.sources and q.sources[-1].experiment_id == b for q in appeared)
    # #018 is the passing baseline: no criteria failure (critical) or IS suppression resolves.
    resolved = [q for q in d.qc_changes if q.change == "resolved"]
    assert not [q for q in resolved if q.severity == "critical" or q.code == "is_suppression"]
    # informational flags (e.g. ``loq_above_lowest_level``) never mix into ``qc_changes``
    assert all(q.severity != "info" for q in d.qc_changes)
    assert d.qc_info_changes and all(q.severity == "info" for q in d.qc_info_changes)


def test_reverse_diff_marks_flags_resolved(session: Session, seeded: dict[str, int]) -> None:
    d = service.diff(session, seeded["#024"], seeded["#018"])
    failures = [q for q in d.qc_changes if q.severity == "critical" or q.code == "is_suppression"]
    assert failures and {q.change for q in failures} == {"resolved"}
    assert all(q.severity != "info" for q in d.qc_changes)
    rec = next(r for r in d.result_changes if r.metric == "recovery_mean_pct")
    assert rec.delta is not None and rec.delta > 20


def test_info_flags_are_classified_apart_from_qc_changes() -> None:
    """``severity == "info"`` flags go to ``qc_info_changes``, never appeared/resolved QC."""
    src = SourceRef(ref_type="analysis.AnalysisResult", ref_id=1, field="flags[0]")

    def fact(code: str, severity: str, analyte: str) -> QCFact:
        return QCFact(code=code, severity=severity, analyte=analyte, source=src)

    a = [
        fact("loq_above_lowest_level", "info", "x"),
        fact("recovery_out_of_range", "critical", "y"),
    ]
    b = [fact("loq_above_lowest_level", "info", "z")]
    qc, info = service.split_info_changes(service.qc_changes(a, b))
    assert [(q.code, q.change) for q in qc] == [("recovery_out_of_range", "resolved")]
    assert sorted((q.analyte, q.change) for q in info) == [("x", "resolved"), ("z", "appeared")]


def test_diff_without_providers_is_structural_only(
    session: Session, seeded: dict[str, int], no_providers: None
) -> None:
    d = service.diff(session, seeded["#018"], seeded["#024"])
    assert not d.results_available
    assert d.result_changes == [] and d.qc_changes == []
    assert len(d.condition_changes) == 2


def test_diff_relations(session: Session, seeded: dict[str, int]) -> None:
    sib = service.diff(session, seeded["#019"], seeded["#024"])
    assert sib.relation == "siblings" and sib.common_ancestor_id == seeded["#018"]
    child = service.diff(session, seeded["#024"], seeded["#018"])
    assert child.relation == "b_is_ancestor"
    same = service.diff(session, seeded["#018"], seeded["#018"])
    assert same.relation == "same" and same.condition_changes == []


def test_diff_unrelated_and_added_removed_keys(session: Session, seeded: dict[str, int]) -> None:
    from datetime import date

    from app.eln import service as eln
    from app.eln.schemas import ConditionBlock, ExperimentCreate, ProjectCreate

    other = eln.create_project(session, ProjectCreate(name="다른 프로젝트"))
    exp = eln.create_experiment(
        session,
        other.id,
        ExperimentCreate(
            code="#001",
            title="균주 배양",
            performed_on=date(2026, 10, 1),
            raw_note="E. coli 배양",
            condition_block=ConditionBlock.model_validate({"strain": "E. coli K-12", "ph": 7.0}),
        ),
    )
    d = service.diff(session, seeded["#018"], exp.id)
    assert d.relation == "unrelated" and d.common_ancestor_id is None
    kinds = {c.key: c.change for c in d.condition_changes}
    assert kinds["strain"] == "added" and kinds["matrix"] == "removed" and kinds["ph"] == "changed"
    added = next(c for c in d.condition_changes if c.key == "strain")
    assert [s.ref_id for s in added.sources] == [exp.id]


def test_word_level_note_diff_isolates_number_change() -> None:
    assert tokenize("추출 10분") == ["추출", " ", "10", "분"]
    old, new = word_segments("추출 시간 10분 유지", "추출 시간 5분 유지")
    assert [s.text for s in old if s.op == "delete"] == ["10"]
    assert [s.text for s in new if s.op == "insert"] == ["5"]
    assert "".join(s.text for s in new) == "추출 시간 5분 유지"


def test_note_diff_pairs_replaced_lines_only() -> None:
    lines = note_diff("a\n추출 10분\nb", "a\n추출 5분\nb\nc 추가")
    changed = [line for line in lines if line.op != "equal"]
    assert [(line.op, bool(line.segments)) for line in changed] == [
        ("delete", True),
        ("insert", True),
        ("insert", False),
    ]
    deleted_only = note_diff("x\ny", "x")
    assert [(line.op, line.segments) for line in deleted_only] == [
        ("equal", []),
        ("delete", []),
    ]


def test_seed_note_diff_has_segments(session: Session, seeded: dict[str, int]) -> None:
    d = service.diff(session, seeded["#018"], seeded["#024"])
    segs = [s for line in d.note_diff for s in line.segments]
    assert any(s.op == "delete" for s in segs) and any(s.op == "insert" for s in segs)
