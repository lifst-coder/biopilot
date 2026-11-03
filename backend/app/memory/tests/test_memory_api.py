"""Memory HTTP contract."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_memory_endpoints(client: TestClient) -> None:
    diff = client.get("/api/memory/diff", params={"a": 1, "b": 7})
    assert diff.status_code == 200
    body = diff.json()
    assert {c["key"] for c in body["condition_changes"]} == {
        "extraction_time_min",
        "cleanup_sorbent",
    }
    rec = next(r for r in body["result_changes"] if r["metric"] == "recovery_mean_pct")
    assert rec["delta"] < 0 and {s["experiment_id"] for s in rec["sources"]} == {1, 7}
    assert len(client.get("/api/memory/projects/1/timeline").json()) == 7
    assert len(client.get("/api/memory/projects/1/graph").json()["edges"]) == 6
    rel = client.get("/api/memory/projects/1/graph", params={"relations": "shares_conditions"})
    assert {e["relation"] for e in rel.json()["edges"]} == {"shares_conditions"}
    hits = client.get("/api/memory/projects/1/search", params={"q": "회수율"}).json()
    assert hits and "score" in hits[0] and "highlights" in hits[0]
    assert len(client.get("/api/memory/experiments/7/lineage").json()) == 2
    created = client.post("/api/memory/experiments/1/digests")
    assert created.status_code == 201 and created.json()["engine"] == "rules"
    assert len(client.get("/api/memory/experiments/1/digests").json()) == 2
    assert client.get("/api/memory/diff", params={"a": 1, "b": 999}).status_code == 404


def test_knowledge_graph_recall_ask_similar(client: TestClient) -> None:
    g = client.get("/api/memory/projects/1/knowledge-graph").json()
    assert g["counts"]["experiment"] == 7 and g["refresh"]["mode"] in ("full", "incremental")
    only = client.get(
        "/api/memory/projects/1/knowledge-graph", params={"types": ["experiment", "result"]}
    ).json()
    assert set(only["counts"]) == {"experiment", "result"}
    focus = client.get(
        "/api/memory/projects/1/knowledge-graph", params={"focus": "experiment:7", "radius": 1}
    )
    assert focus.status_code == 200
    assert (
        client.get("/api/memory/projects/1/knowledge-graph", params={"focus": "nope:1"}).status_code
        == 404
    )
    recall = client.get("/api/memory/projects/1/recall", params={"q": "GCB carbendazim"}).json()
    assert recall["experiments"][0]["experiment"]["code"] == "#024"
    ask = client.post("/api/memory/projects/1/ask", json={"question": "GCB 회수율"})
    assert ask.status_code == 200 and ask.json()["engine"] == "rules" and ask.json()["fragments"]
    assert client.post("/api/memory/projects/1/ask", json={"question": ""}).status_code == 422
    sim = client.get("/api/memory/experiments/7/similar", params={"limit": 2}).json()
    assert len(sim) == 2 and sim[0]["score"] >= sim[1]["score"]


def test_conditions_endpoints(client: TestClient) -> None:
    hist = client.get("/api/memory/projects/1/conditions/extraction_time_min/history").json()
    assert [h["value"] for h in hist][-2:] == [10.0, 5.0]
    assert client.get("/api/memory/projects/1/conditions/unknown/history").json() == []
    m = client.get("/api/memory/compare-conditions", params={"ids": "1,2,7", "varying_only": True})
    assert m.status_code == 200 and {r["key"] for r in m.json()["rows"]} >= {
        "ph",
        "cleanup_sorbent",
    }
    bad = client.get("/api/memory/compare-conditions", params={"ids": "1,x"})
    assert bad.status_code == 400 and bad.json()["code"] == "validation_failed"
    assert client.get("/api/memory/compare-conditions", params={"ids": ","}).status_code == 400


def test_knowledge_notes_endpoints(client: TestClient) -> None:
    created = client.post(
        "/api/memory/projects/1/knowledge-notes",
        json={"statement": "GCB는 평면 분자를 흡착", "linked_experiment_ids": [7]},
    )
    assert created.status_code == 201
    listing = client.get("/api/memory/projects/1/knowledge-notes").json()
    assert listing["total"] == 1 and listing["items"][0]["linked_experiment_ids"] == [7]
    bad = client.post(
        "/api/memory/projects/1/knowledge-notes",
        json={"statement": "x", "linked_experiment_ids": [999]},
    )
    assert bad.status_code == 400
    empty = client.post(
        "/api/memory/projects/1/knowledge-notes",
        json={"statement": "x", "linked_experiment_ids": []},
    )
    assert empty.status_code == 422
    hits = client.get("/api/memory/projects/1/search", params={"q": "평면 분자"}).json()
    assert [h["field"] for h in hits] == ["knowledge_note"]
