"""The scale benchmark's response dump/compare (PERFORMANCE.md reproduction)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.scripts import bench_scale

REPORT = {
    "experiments": 7,
    "datasets": 9,
    "analysis_results": 20,
    "audit_events": 50,
    "repeats": 1,
}


def test_normalized_drops_write_timestamps_at_any_depth() -> None:
    body = {"id": 1, "created_at": "t", "items": [{"occurred_at": "t", "v": 2.5}]}
    assert bench_scale.normalized(body) == {"id": 1, "items": [{"v": 2.5}]}


def test_compare_flags_differences_and_refuses_other_runs(tmp_path: Path) -> None:
    responses = {"a": {"x": 1, "created_at": "t1"}, "b": [1, 2]}
    bench_scale.dump(responses, tmp_path, REPORT)
    same = {"a": {"x": 1, "created_at": "t2"}, "b": [1, 2]}
    assert bench_scale.compare(same, tmp_path, REPORT) == []
    assert bench_scale.compare({"a": {"x": 2}, "b": [1, 2]}, tmp_path, REPORT) == ["a"]
    assert bench_scale.compare({"c": 1}, tmp_path, REPORT) == [f"c (missing in {tmp_path})"]
    with pytest.raises(SystemExit):
        bench_scale.compare(same, tmp_path, {**REPORT, "repeats": 5})


def test_slug_is_a_file_name() -> None:
    assert bench_scale.slug("GET search q=GCB 정제 (2 terms)") == "get_search_q_gcb_정제_2_terms"
