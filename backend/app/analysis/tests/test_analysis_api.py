"""Analysis HTTP contract."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_compare_trend_and_results(client: TestClient) -> None:
    criteria = client.get("/api/analysis/criteria").json()
    assert criteria["recovery_min_pct"] == 70
    metrics = client.get("/api/analysis/experiments/7/metrics").json()
    assert metrics["analyzed"] is True and metrics["source_result_ids"]
    results = client.get("/api/analysis/results", params={"experiment_id": 7}).json()
    kinds = {r["kind"] for r in results}
    assert kinds == {"calibration", "recovery", "is_response"}
    one = client.get(f"/api/analysis/results/{results[0]['id']}").json()
    assert one["output"]["kind"] == one["kind"]
    cmp = client.get("/api/analysis/compare", params={"a": 1, "b": 7}).json()
    assert cmp["recovery_t_test"]["p_value"] < 0.001
    assert len(client.get("/api/analysis/projects/1/trend").json()) == 7
    run = client.post("/api/analysis/experiments/1/run").json()
    assert run["created"] == 0
