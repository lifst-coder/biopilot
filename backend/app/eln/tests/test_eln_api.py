"""ELN HTTP contract against the seeded app."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_seeded_project_and_experiments(client: TestClient) -> None:
    projects = client.get("/api/eln/projects").json()
    assert len(projects) == 1 and projects[0]["experiment_count"] == 7
    exps = client.get(f"/api/eln/projects/{projects[0]['id']}/experiments").json()
    assert [e["code"] for e in exps] == [f"#0{n}" for n in range(18, 25)]
    assert "raw_note" not in exps[0]


def test_experiment_detail_and_datasets(client: TestClient) -> None:
    exp = client.get("/api/eln/experiments/7").json()
    assert exp["code"] == "#024"
    assert exp["condition_block"]["extraction_time_min"] == 5
    datasets = client.get("/api/eln/experiments/7/datasets").json()
    assert {d["kind"] for d in datasets} == {"calibration", "recovery"}
    preview = client.get(f"/api/eln/datasets/{datasets[0]['id']}", params={"limit": 3}).json()
    assert len(preview["rows"]) == 3
    raw = client.get(f"/api/eln/datasets/{datasets[0]['id']}/content")
    assert raw.status_code == 200 and raw.text.startswith("injection_id,")


def test_create_experiment_and_errors(client: TestClient) -> None:
    body = {
        "code": "#025",
        "title": "new",
        "performed_on": "2026-10-27",
        "parent_experiment_id": 7,
        "raw_note": "note",
        "condition_block": {"extraction_time_min": 10},
    }
    created = client.post("/api/eln/projects/1/experiments", json=body)
    assert created.status_code == 201
    dup = client.post("/api/eln/projects/1/experiments", json=body)
    assert dup.status_code == 400 and dup.json()["code"] == "validation_failed"
    missing = client.get("/api/eln/experiments/9999")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_condition_fields_cover_seed_keys(client: TestClient) -> None:
    keys = {f["key"] for f in client.get("/api/eln/condition-fields").json()}
    exp = client.get("/api/eln/experiments/1").json()
    assert set(exp["condition_block"]) <= keys
