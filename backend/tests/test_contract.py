"""API contract: committed OpenAPI is current, ids are unique, every GET answers."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.scripts.export_openapi import OPENAPI_PATH, render

PATH_PARAMS = {
    "project_id": "1",
    "experiment_id": "7",
    "dataset_id": "1",
    "result_id": "1",
    "critique_id": "1",
    "proposal_id": "1",
    "key": "extraction_time_min",
    "run_id": "1",
}
QUERY_PARAMS: dict[str, dict[str, str | int]] = {
    "/api/analysis/compare": {"a": 1, "b": 7},
    "/api/memory/diff": {"a": 1, "b": 7},
    "/api/memory/projects/{project_id}/search": {"q": "GCB"},
    "/api/memory/projects/{project_id}/recall": {"q": "GCB carbendazim"},
    "/api/memory/compare-conditions": {"ids": "1,2,7"},
    "/api/memory/search": {"q": "GCB"},
    "/api/memory/recall": {"q": "GCB carbendazim"},
    "/api/analysis/records/conditions": {"key": "cleanup_sorbent"},
    "/api/partner/hypotheses": {"project_id": 1},
    "/api/partner/proposals": {"project_id": 1},
    "/api/eln/protocol-diff": {"a": 1, "b": 2},
}


def _protocol_records(client: TestClient) -> None:
    """The reference seed has no protocols: save two versions and start a run (ids 1, 2)."""
    for source in (1, 7):
        res = client.post(
            "/api/eln/projects/1/protocol-templates",
            json={"name": "SOP", "source_experiment_id": source},
        )
        assert res.status_code == 201
    assert client.post("/api/eln/protocol-templates/1/runs", json={}).status_code == 201


def test_committed_openapi_is_up_to_date() -> None:
    assert OPENAPI_PATH.exists(), "run: python -m app.scripts.export_openapi"
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(), (
        "openapi.json is stale — run `python -m app.scripts.export_openapi` "
        "and `npm run gen:api` in frontend/"
    )


def test_operation_ids_unique_and_prefixed(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))
    assert all(re.match(r"^(system|eln|memory|analysis|partner)_", i) for i in ids)


def test_every_get_endpoint_returns_real_data(client: TestClient) -> None:
    _protocol_records(client)
    spec = client.get("/openapi.json").json()
    for path, item in spec["paths"].items():
        if "get" not in item:
            continue
        url = path
        for name, value in PATH_PARAMS.items():
            url = url.replace("{" + name + "}", value)
        response = client.get(url, params=QUERY_PARAMS.get(path, {}))
        assert response.status_code == 200, f"GET {url} -> {response.status_code}"
        if response.headers["content-type"].startswith("application/json"):
            assert response.json() not in (None, [], {}), f"GET {url} returned empty payload"
