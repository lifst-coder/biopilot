"""Analysis HTTP contract."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_compare_trend_and_results(client: TestClient) -> None:
    criteria = client.get("/api/analysis/criteria").json()
    assert criteria["recovery_min_pct"] == 70
    metrics = client.get("/api/analysis/experiments/7/metrics").json()
    assert metrics["analyzed"] is True and metrics["source_result_ids"]
    assert metrics["qc_status"] == "fail"
    results = client.get("/api/analysis/results", params={"experiment_id": 7}).json()
    kinds = {r["kind"] for r in results}
    assert kinds == {"calibration", "limits", "recovery", "is_response"}
    one = client.get(f"/api/analysis/results/{results[0]['id']}").json()
    assert one["output"]["kind"] == one["kind"]
    assert one["output"]["method"]["formulas"]
    cmp = client.get("/api/analysis/compare", params={"a": 1, "b": 7}).json()
    assert cmp["recovery_t_test"]["p_value"] < 0.001
    assert cmp["recovery_t_test"]["hedges_g"] < 0
    assert set(cmp["significant_analytes"]) >= {"carbendazim", "thiabendazole"}
    assert cmp["method"]["assumptions"]
    assert len(client.get("/api/analysis/projects/1/trend").json()) == 7
    run = client.post("/api/analysis/experiments/1/run").json()
    assert run["created"] == 0
    assert client.get("/api/analysis/results/99999").status_code == 404


def test_methods_endpoint_lists_every_kind(client: TestClient) -> None:
    docs = client.get("/api/analysis/methods").json()
    kinds = {d["kind"] for d in docs}
    assert kinds == {
        "calibration",
        "recovery",
        "is_response",
        "matrix_effect",
        "limits",
        "ion_ratio",
        "comparison",
    }
    assert all(d["formulas"] and d["assumptions"] for d in docs)


def test_project_criteria_versioning_over_http(client: TestClient) -> None:
    current = client.get("/api/analysis/projects/1/criteria").json()
    assert current["active"]["version"] == 0 and current["active"]["label"] == "default"
    body = {"criteria": {"recovery_min_pct": 60, "rsd_max_pct": 15}, "note": "내부 기준"}
    created = client.post("/api/analysis/projects/1/criteria", json=body)
    assert created.status_code == 201
    assert created.json()["label"] == "project-1@v1"
    after = client.get("/api/analysis/projects/1/criteria").json()
    assert [h["version"] for h in after["history"]] == [0, 1]
    assert (
        client.get("/api/analysis/criteria", params={"project_id": 1}).json()["recovery_min_pct"]
        == 60
    )
    bad = {"criteria": {"recovery_min_pct": 130, "recovery_max_pct": 70}}
    assert client.post("/api/analysis/projects/1/criteria", json=bad).status_code == 422
    assert client.get("/api/analysis/projects/999/criteria").status_code == 404
    rerun = client.post("/api/analysis/experiments/7/run").json()
    assert rerun["created"] == len(rerun["results"])  # new criteria → new results
    labels = {f["criteria_version"] for r in rerun["results"] for f in r["flags"]}
    assert labels == {"project-1@v1"}
    audit = client.get(
        "/api/audit", params={"project_id": 1, "entity_type": "analysis.AnalysisCriteriaVersion"}
    ).json()
    assert audit and audit[0]["action"] == "analysis.criteria.create"


def test_report_export_markdown_and_csv(client: TestClient) -> None:
    md = client.get("/api/analysis/experiments/7/report")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert 'filename="biopilot-024-analysis.md"' in md.headers["content-disposition"]
    assert "# 분석 리포트 — #024" in md.text and "**공식**" in md.text
    csv = client.get("/api/analysis/experiments/7/report", params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv")
    header, *rows = csv.text.strip().splitlines()
    assert header == "section,result_id,method_version,analyte,key,metric,value,unit"
    assert any(r.startswith("flag,") and "is_suppression" in r for r in rows)
    assert client.get("/api/analysis/experiments/7/report", params={"format": "x"}).status_code == (
        422
    )
