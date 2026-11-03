"""Partner HTTP contract (rules mode, no API key)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_partner_endpoints(client: TestClient) -> None:
    assert client.get("/api/partner/mode").json()["mode"] == "rules"
    crit = client.post("/api/partner/experiments/7/critiques")
    assert crit.status_code == 201
    body = crit.json()
    assert body["engine"] == "rules" and body["findings"][0]["severity"] == "critical"
    keys = {e["key"] for e in body["evidence"]}
    assert all(k in keys for f in body["findings"] for k in f["evidence_keys"])
    assert len(client.get("/api/partner/experiments/7/critiques").json()) == 2
    assert client.get(f"/api/partner/critiques/{body['id']}").status_code == 200
    props = client.get("/api/partner/proposals", params={"project_id": 1}).json()
    pid = props[0]["id"]
    decided = client.post(
        f"/api/partner/proposals/{pid}/decision", json={"action": "reject", "rationale": "no"}
    )
    assert decided.status_code == 201 and decided.json()["status"] == "rejected"
    assert client.get(f"/api/partner/proposals/{pid}").json()["decision"]["action"] == "reject"
    bad = client.post(
        f"/api/partner/proposals/{props[1]['id']}/decision",
        json={"action": "modify", "rationale": "x"},
    )
    assert bad.status_code == 422
    hyps = client.get("/api/partner/hypotheses", params={"project_id": 1}).json()
    assert len(hyps) >= 3
    created = client.post(
        "/api/partner/hypotheses", json={"project_id": 1, "statement": "사용자 가설"}
    )
    assert created.status_code == 201
    ask = client.post(
        "/api/partner/ask", json={"project_id": 1, "experiment_id": 7, "question": "회수율?"}
    ).json()
    assert ask["engine"] == "rules" and ask["evidence"]
