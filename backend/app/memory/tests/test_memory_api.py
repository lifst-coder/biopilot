"""Memory HTTP contract."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_memory_endpoints(client: TestClient) -> None:
    diff = client.get("/api/memory/diff", params={"a": 1, "b": 7})
    assert diff.status_code == 200
    assert {c["key"] for c in diff.json()["condition_changes"]} == {
        "extraction_time_min",
        "cleanup_sorbent",
    }
    assert len(client.get("/api/memory/projects/1/timeline").json()) == 7
    assert len(client.get("/api/memory/projects/1/graph").json()["edges"]) == 6
    assert client.get("/api/memory/projects/1/search", params={"q": "IS"}).status_code == 200
    assert len(client.get("/api/memory/experiments/7/lineage").json()) == 2
    created = client.post("/api/memory/experiments/1/digests")
    assert created.status_code == 201 and created.json()["engine"] == "rules"
    assert len(client.get("/api/memory/experiments/1/digests").json()) == 2
    assert client.get("/api/memory/diff", params={"a": 1, "b": 999}).status_code == 404
