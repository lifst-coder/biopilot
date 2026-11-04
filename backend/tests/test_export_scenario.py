"""Demo scenario exporter: canonical keys (shared with frontend/src/api/demo.ts) and replay data."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.scripts.export_scenario import Recorder, request_key


def test_request_key_matches_the_demo_adapter() -> None:
    assert (
        request_key("/api/memory/diff", {"b": 7, "a": 1, "limit": 20}) == "/api/memory/diff?a=1&b=7"
    )
    assert request_key("/api/partner/proposals", {"project_id": 1, "experiment_id": None}) == (
        "/api/partner/proposals?project_id=1"
    )
    assert request_key("/api/memory/projects/1/search", {"q": "추출 시간"}) == (
        "/api/memory/projects/1/search?q=%EC%B6%94%EC%B6%9C+%EC%8B%9C%EA%B0%84"
    )


def test_recorder_keeps_real_responses_and_replays_client_errors(client: TestClient) -> None:
    rec = Recorder(client)
    projects = rec.get("/api/eln/projects")
    assert projects == client.get("/api/eln/projects").json()
    metrics = rec.get("/api/analysis/experiments/7/metrics")
    assert (
        metrics["recovery_mean_pct"]
        == client.get("/api/analysis/experiments/7/metrics").json()["recovery_mean_pct"]
    )
    assert rec.get("/api/eln/experiments/99999") is None
    assert rec.errors["/api/eln/experiments/99999"]["status"] == 404
    assert rec.failures == []


def test_recorder_keeps_report_downloads_with_their_headers(client: TestClient) -> None:
    rec = Recorder(client)
    rec.get_text("/api/analysis/experiments/7/report", {"format": "csv"})
    saved = rec.texts["/api/analysis/experiments/7/report?format=csv"]
    live = client.get("/api/analysis/experiments/7/report", params={"format": "csv"})
    assert saved["body"] == live.text
    assert saved["content_type"].startswith("text/csv")
    assert "filename=" in saved["content_disposition"]
    assert rec.failures == []


def test_protocol_example_extraction_leaves_the_range_empty(client: TestClient) -> None:
    from app.scripts.export_scenario import PROTOCOL_EXAMPLE

    res = client.post("/api/eln/protocol-extractions", json={"text": PROTOCOL_EXAMPLE})
    assert res.status_code == 200
    fields = {f["key"]: f for f in res.json()["fields"]}
    assert fields["cleanup_sorbent"]["status"] == "recognized"
    assert fields["extraction_time_min"]["value"] is None  # "5~10분" is a range: not guessed
