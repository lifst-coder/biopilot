"""End-to-end ELN workflows over HTTP: authoring, uploads, corrections, history, audit."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.eln import csv_ingest, storage

DATA = Path(__file__).parent / "data"
CAL = (
    "injection_id,level_ng_ml,analyte,analyte_area,is_area\n"
    "C1,1,azoxystrobin,100,1000\nC2,2,azoxystrobin,200,1000\n"
)


def _new_experiment(client: TestClient, code: str = "#900", **extra: Any) -> dict[str, Any]:
    body = {
        "code": code,
        "title": "새 실험",
        "author": "박연구",
        "performed_on": "2026-11-01",
        "parent_experiment_id": 7,
        "raw_note": "목적: 테스트\n관찰:\n- 원본 메모",
        "condition_block": {
            "matrix": "사과",
            "sample_mass_g": 10,
            "extraction_solvent": "MeCN",
            "extraction_time_min": 10,
            "cleanup_sorbent": "PSA",
            "column": "C18",
            "internal_standard": "TPP",
        },
        **extra,
    }
    response = client.post("/api/eln/projects/1/experiments", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _upload(
    client: TestClient,
    exp_id: int,
    content: bytes,
    *,
    kind: str = "calibration",
    filename: str = "cal.csv",
    path: str = "datasets/upload",
    **fields: str,
) -> Any:
    return client.post(
        f"/api/eln/experiments/{exp_id}/{path}",
        files={"file": (filename, content, "text/csv")},
        data={"kind": kind, **fields},
    )


def _audit(client: TestClient, exp_id: int) -> list[dict[str, Any]]:
    return list(client.get(f"/api/eln/experiments/{exp_id}/audit").json())


# ------------------------------------------------------------- authoring


def test_create_with_template_warning_and_error(client: TestClient) -> None:
    exp = _new_experiment(client)
    assert exp["warnings"] == []
    warn = client.post(
        "/api/eln/projects/1/experiments",
        json={
            "code": "#901",
            "title": "t",
            "performed_on": "2026-11-01",
            "raw_note": "n",
            "condition_block": {"ph": 11, "extraction_time_min": 10},
        },
    )
    assert warn.status_code == 201
    codes = {(w["key"], w["code"]) for w in warn.json()["warnings"]}
    assert ("ph", "outside_usual") in codes and ("matrix", "required_missing") in codes
    error = client.post(
        "/api/eln/projects/1/experiments",
        json={
            "code": "#902",
            "title": "t",
            "performed_on": "2026-11-01",
            "raw_note": "n",
            "condition_block": {"ph": 15},
        },
    )
    assert error.status_code == 400 and "pH" in error.json()["message"]
    assert error.json()["code"] == "validation_failed"


def test_condition_check_and_project_template_versions(client: TestClient) -> None:
    default = client.get("/api/eln/projects/1/condition-template").json()
    assert default["source"] == "default" and default["version"] == 0
    check = client.post("/api/eln/projects/1/condition-check", json={"ph": -1}).json()
    assert check["ok"] is False and check["template_source"] == "default"
    created = client.post(
        "/api/eln/projects/1/condition-template",
        json={
            "rules": [{"key": "matrix", "required": True, "required_level": "error"}],
            "note": "엄격",
        },
    )
    assert created.status_code == 201 and created.json()["version"] == 1
    assert client.post("/api/eln/projects/1/condition-check", json={}).json()["ok"] is False
    blocked = client.post(
        "/api/eln/projects/1/experiments",
        json={
            "code": "#903",
            "title": "t",
            "performed_on": "2026-11-01",
            "raw_note": "n",
            "condition_block": {},
        },
    )
    assert blocked.status_code == 400
    again = client.post(
        "/api/eln/projects/1/condition-template",
        json={"rules": [{"key": "ph", "min": 0, "max": 14}]},
    )
    assert again.json()["version"] == 2
    dup = client.post(
        "/api/eln/projects/1/condition-template",
        json={"rules": [{"key": "ph"}, {"key": "ph"}]},
    )
    assert dup.status_code == 400
    inverted = client.post(
        "/api/eln/projects/1/condition-template",
        json={"rules": [{"key": "ph", "min": 5, "max": 1}]},
    )
    assert inverted.status_code == 400
    events = client.get(
        "/api/audit", params={"entity_type": "eln.ConditionTemplate", "project_id": 1}
    ).json()
    assert [e["payload"]["version"] for e in events] == [2, 1]


def test_full_authoring_flow_is_audited(client: TestClient) -> None:
    exp = _new_experiment(client)
    ds = _upload(client, exp["id"], CAL.encode())
    assert ds.status_code == 201, ds.text
    assert ds.json()["schema_ref"] == "calibration@1"
    addendum = client.post(
        f"/api/eln/experiments/{exp['id']}/addenda", json={"note": "보충", "author": "박연구"}
    )
    assert addendum.status_code == 201
    patched = client.patch(
        f"/api/eln/experiments/{exp['id']}/metadata", json={"title": "새 제목", "reason": "오타"}
    )
    assert patched.status_code == 200 and patched.json()["revision"] == 2
    attach = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("chrom.png", b"\x89PNG\r\n\x1a\nbinary", "image/png")},
        data={"description": "크로마토그램"},
    )
    assert attach.status_code == 201
    digest = client.post(f"/api/memory/experiments/{exp['id']}/digests")
    assert digest.status_code == 201
    actions = {(e["entity_type"], e["action"]) for e in _audit(client, exp["id"])}
    assert actions >= {
        ("eln.Experiment", "create"),
        ("eln.Dataset", "create"),
        ("eln.ExperimentAddendum", "add_addendum"),
        ("eln.Experiment", "update_metadata"),
        ("eln.AttachmentFile", "attach_file"),
        ("memory.ExperimentDigest", "memory.digest"),
    }
    full = client.get(f"/api/eln/experiments/{exp['id']}").json()
    assert full["raw_note"] == "목적: 테스트\n관찰:\n- 원본 메모"
    assert [a["note"] for a in full["addenda"]] == ["보충"]
    assert full["attachment_files"][0]["download_url"].endswith("/content")


# --------------------------------------------------------------- uploads


def test_multipart_upload_utf8_and_cp949_match_json_hash(client: TestClient) -> None:
    exp = _new_experiment(client)
    korean = CAL.replace("azoxystrobin", "아족시스트로빈")
    via_json = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets",
        json={"kind": "calibration", "filename": "j.csv", "content": korean},
    ).json()
    utf8 = _upload(client, exp["id"], korean.encode("utf-8")).json()
    cp949 = _upload(client, exp["id"], korean.encode("cp949")).json()
    bom = _upload(client, exp["id"], b"\xef\xbb\xbf" + korean.encode()).json()
    assert via_json["sha256"] == utf8["sha256"] == cp949["sha256"] == bom["sha256"]
    assert via_json["sha256"] == hashlib.sha256(korean.encode()).hexdigest()
    assert (utf8["source_encoding"], cp949["source_encoding"], bom["source_encoding"]) == (
        "utf-8",
        "cp949",
        "utf-8-sig",
    )
    content = client.get(f"/api/eln/datasets/{cp949['id']}/content").text
    assert content == korean
    events = client.get("/api/audit", params={"entity_type": "eln.Dataset", "limit": 3}).json()
    assert events[1]["payload"]["encoding"] == "cp949"
    raw_hash = hashlib.sha256(korean.encode("cp949")).hexdigest()
    assert events[1]["payload"]["source_sha256"] == raw_hash


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe\xfa\xfb", "인코딩"),
        (b"a,b\x00", "NUL"),
        (b"   ", "빈 파일"),
        (b"injection_id\nA\n", "필수 컬럼 누락"),
    ],
)
def test_upload_rejections(client: TestClient, content: bytes, message: str) -> None:
    exp = _new_experiment(client)
    response = _upload(client, exp["id"], content)
    assert response.status_code == 400 and message in response.json()["message"]


def test_upload_size_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    exp = _new_experiment(client)
    monkeypatch.setattr(csv_ingest, "MAX_CSV_BYTES", 10)
    too_big = _upload(client, exp["id"], CAL.encode())
    assert too_big.status_code == 400 and "너무 큽니다" in too_big.json()["message"]


def test_multipart_body_limit_and_bad_forms(client: TestClient) -> None:
    exp = _new_experiment(client)
    huge = b"x" * (csv_ingest.MAX_CSV_BYTES + 128 * 1024)
    response = _upload(client, exp["id"], huge)
    assert response.status_code == 400 and "너무 큽니다" in response.json()["message"]
    not_form = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets/upload",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert not_form.status_code == 400
    no_file = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets/upload",
        data={"kind": "calibration"},
        files={"other": ("x.csv", b"a", "text/csv")},
    )
    assert no_file.status_code == 400 and "file" in no_file.json()["message"]
    bad_kind = _upload(client, exp["id"], CAL.encode(), kind="spectra")
    assert bad_kind.status_code == 400
    bad_int = _upload(client, exp["id"], CAL.encode(), supersedes_dataset_id="x")
    assert bad_int.status_code == 400
    no_kind = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets/upload",
        files={"file": ("cal.csv", CAL.encode(), "text/csv")},
    )
    assert no_kind.status_code == 400 and "kind" in no_kind.json()["message"]


def test_reupload_supersedes_but_keeps_previous(client: TestClient) -> None:
    exp = _new_experiment(client)
    first = _upload(client, exp["id"], CAL.encode()).json()
    fixed = CAL.replace("200,1000", "210,1000")
    second = _upload(
        client, exp["id"], fixed.encode(), supersedes_dataset_id=str(first["id"])
    ).json()
    assert second["supersedes_dataset_id"] == first["id"]
    listed = client.get(f"/api/eln/experiments/{exp['id']}/datasets").json()
    assert [d["id"] for d in listed] == [first["id"], second["id"]]
    assert listed[0]["superseded_by_dataset_id"] == second["id"]
    assert client.get(f"/api/eln/datasets/{first['id']}/content").text == CAL
    actions = [e["action"] for e in _audit(client, exp["id"]) if e["entity_type"] == "eln.Dataset"]
    assert actions == ["reupload", "create"]
    wrong_kind = _upload(
        client,
        exp["id"],
        b"a\n1\n",
        kind="other",
        supersedes_dataset_id=str(first["id"]),
    )
    assert wrong_kind.status_code == 400
    other_exp = _upload(client, 7, CAL.encode(), supersedes_dataset_id=str(first["id"]))
    assert other_exp.status_code == 400


def test_validate_endpoints_store_nothing(client: TestClient) -> None:
    before = len(client.get("/api/audit", params={"limit": 1000}).json())
    bad = CAL.replace("azoxystrobin", "아족시") + "C3,x,아족시,1,1\n"
    report = client.post(
        "/api/eln/datasets/validate-upload",
        files={"file": ("bad.csv", bad.encode("cp949"), "text/csv")},
        data={"kind": "calibration"},
    ).json()
    assert report["ok"] is False and report["encoding"] == "cp949"
    assert report["row_count"] == 3 and len(report["preview_rows"]) == 3
    assert {"row": 3, "column": "level_ng_ml"}.items() <= report["issues"][0].items()
    text_report = client.post(
        "/api/eln/datasets/validate",
        json={"kind": "calibration", "filename": "x.csv", "content": 'a,"b\n'},
    ).json()
    assert text_report["ok"] is False and text_report["issues"][0]["code"] == "parse_error"
    ok = client.post(
        "/api/eln/datasets/validate",
        json={"kind": "calibration", "filename": "x.csv", "content": CAL},
    ).json()
    assert ok["ok"] is True and ok["schema_ref"] == "calibration@1"
    unknown_version = client.post(
        "/api/eln/datasets/validate",
        json={"kind": "calibration", "filename": "x.csv", "content": CAL, "schema_version": 9},
    )
    assert unknown_version.status_code == 400
    assert len(client.get("/api/audit", params={"limit": 1000}).json()) == before


def test_ion_ratio_kind_is_accepted(client: TestClient) -> None:
    exp = _new_experiment(client)
    content = (
        "injection_id,sample_type,analyte,quantifier_area,qualifier_area\n"
        "I1,standard,x,1000,450\nI2,sample,x,900,410\n"
    )
    ds = _upload(client, exp["id"], content.encode(), kind="ion_ratio").json()
    assert ds["schema_ref"] == "ion_ratio@1"
    assert client.get(f"/api/eln/experiments/{exp['id']}").json()["dataset_kinds"] == ["ion_ratio"]
    kinds = {s["kind"] for s in client.get("/api/eln/dataset-kinds").json()}
    assert "ion_ratio" in kinds


# -------------------------------------------------------------- vendor import


def test_import_preview_and_import_keep_original(client: TestClient, eln_storage: Path) -> None:
    exp = _new_experiment(client)
    raw = (DATA / "vendor_report_recovery.csv").read_bytes()
    formats = {f["name"] for f in client.get("/api/eln/import-formats").json()}
    assert formats == {"wide_analyte_columns", "compound_area_suffix"}
    preview = client.post(
        "/api/eln/import/preview",
        files={"file": ("report.csv", raw, "text/csv")},
        data={"kind": "recovery", "format": "compound_area_suffix"},
    ).json()
    assert preview["validation"]["ok"] is True and preview["source_rows"] == 4
    assert preview["validation"]["row_count"] == 4  # 2 spiked injections × 2 analytes
    stored = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets/import",
        files={"file": ("report.csv", raw, "text/csv")},
        data={"kind": "recovery", "format": "compound_area_suffix"},
    )
    assert stored.status_code == 201, stored.text
    ds = stored.json()
    assert ds["filename"] == "report.long.csv" and ds["source_attachment_id"] is not None
    original = client.get(f"/api/eln/attachment-files/{ds['source_attachment_id']}/content")
    assert original.content == raw
    bad = client.post(
        "/api/eln/import/preview",
        files={"file": ("report.csv", raw, "text/csv")},
        data={"kind": "recovery", "format": "unknown"},
    )
    assert bad.status_code == 400
    invalid = client.post(
        f"/api/eln/experiments/{exp['id']}/datasets/import",
        files={"file": ("w.csv", b"Injection,Level,IS Area,x\nA,abc,1,2\n", "text/csv")},
        data={"kind": "calibration", "format": "wide_analyte_columns"},
    )
    assert invalid.status_code == 400 and "숫자가 아님" in invalid.json()["message"]


# --------------------------------------------------------------- attachments


def test_attachment_dedup_and_sha(client: TestClient, eln_storage: Path) -> None:
    exp = _new_experiment(client)
    payload = bytes(range(256)) * 10
    first = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("trace.bin", payload, "application/octet-stream")},
    ).json()
    assert first["sha256"] == hashlib.sha256(payload).hexdigest()
    same = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("trace.bin", payload, "application/octet-stream")},
    ).json()
    assert same["id"] == first["id"]
    renamed = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("copy.bin", payload, "application/octet-stream")},
    ).json()
    assert renamed["id"] != first["id"]
    blobs = [p for p in eln_storage.rglob("*") if p.is_file() and p.name != ".gitignore"]
    assert len(blobs) == 1  # one blob on disk for identical bytes
    download = client.get(first["download_url"])
    assert download.content == payload
    assert download.headers["x-content-sha256"] == first["sha256"]
    files_audit = [e for e in _audit(client, exp["id"]) if e["entity_type"] == "eln.AttachmentFile"]
    assert [e["payload"]["blob_reused"] for e in files_audit] == [True, False]
    empty = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("e.bin", b"", "application/octet-stream")},
    )
    assert empty.status_code == 400
    assert client.get("/api/eln/attachment-files/9999/content").status_code == 404
    assert client.delete(first["download_url"]).status_code == 405


def test_attachment_size_limit_and_corruption(
    client: TestClient, eln_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exp = _new_experiment(client)
    ok = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("a.txt", b"hello", "text/plain")},
    ).json()
    storage.blob_path(ok["sha256"]).write_bytes(b"tampered")
    assert client.get(ok["download_url"]).status_code == 400
    storage.blob_path(ok["sha256"]).unlink()
    assert client.get(ok["download_url"]).status_code == 404
    monkeypatch.setattr(storage, "MAX_ATTACHMENT_BYTES", 3)
    big = client.post(
        f"/api/eln/experiments/{exp['id']}/attachment-files",
        files={"file": ("b.txt", b"hello!", "text/plain")},
    )
    assert big.status_code == 400 and "너무 큽니다" in big.json()["message"]


# ------------------------------------------------- metadata, history, audit


def test_metadata_patch_rules(client: TestClient) -> None:
    exp = _new_experiment(client)
    url = f"/api/eln/experiments/{exp['id']}/metadata"
    immutable = client.patch(url, json={"title": "x", "raw_note": "changed"})
    assert immutable.status_code == 409 and immutable.json()["code"] == "immutable_record"
    assert "raw_note" in immutable.json()["message"]
    unknown = client.patch(url, json={"colour": "red"})
    assert unknown.status_code == 400
    unchanged = client.patch(url, json={"title": exp["title"]})
    assert unchanged.status_code == 400
    ok = client.patch(url, json={"title": "고친 제목", "author": "이연구", "reason": "오타"})
    assert ok.status_code == 200
    event = next(e for e in _audit(client, exp["id"]) if e["action"] == "update_metadata")
    assert event["payload"]["changes"] == {
        "title": {"before": "새 실험", "after": "고친 제목"},
        "author": {"before": "박연구", "after": "이연구"},
    }
    assert client.get(f"/api/eln/experiments/{exp['id']}").json()["raw_note"] == exp["raw_note"]


def test_concurrent_metadata_patch_is_409_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ISSUES P1-6: two PATCHes that compute the same revision number → 409, not 500.

    The race is reproduced by making the second request read the revision count the
    first one saw (a stale ``count``), so its insert collides on ``uq_experiment_rev``.
    """
    from app.eln import service as eln_service

    exp = _new_experiment(client)
    url = f"/api/eln/experiments/{exp['id']}/metadata"
    assert client.patch(url, json={"title": "먼저 저장"}).status_code == 200
    monkeypatch.setattr(eln_service, "_revision_count", lambda _s, _id: 1)  # stale
    late = client.patch(url, json={"title": "늦은 저장"})
    assert late.status_code == 409 and late.json()["code"] == "revision_conflict"
    monkeypatch.undo()
    current = client.get(f"/api/eln/experiments/{exp['id']}").json()
    assert current["title"] == "먼저 저장"
    events = [e for e in _audit(client, exp["id"]) if e["action"] == "update_metadata"]
    assert len(events) == 1
    assert client.patch(url, json={"title": "다시 저장"}).status_code == 200


def test_history_reconstructs_versions(client: TestClient) -> None:
    exp = _new_experiment(client)
    url = f"/api/eln/experiments/{exp['id']}/metadata"
    client.patch(url, json={"title": "v2"})
    _upload(client, exp["id"], CAL.encode())
    client.patch(url, json={"title": "v3", "reason": "정정"})
    client.post(f"/api/eln/experiments/{exp['id']}/addenda", json={"note": "추가"})
    history = client.get(f"/api/eln/experiments/{exp['id']}/history").json()
    assert history["current_revision"] == 3
    kinds = [(e["kind"], e["revision"], e["title"]) for e in history["entries"]]
    assert kinds == [
        ("created", 1, "새 실험"),
        ("metadata", 2, "v2"),
        ("dataset", 2, "v2"),
        ("metadata", 3, "v3"),
        ("addendum", 3, "v3"),
    ]
    assert "정정" in history["entries"][3]["summary"]


def test_seeded_experiment_history_and_audit(client: TestClient) -> None:
    history = client.get("/api/eln/experiments/7/history").json()
    assert [e["kind"] for e in history["entries"]] == ["created", "dataset", "dataset"]
    audit = _audit(client, 7)
    types = {e["entity_type"] for e in audit}
    assert {"eln.Experiment", "eln.Dataset", "memory.ExperimentDigest"} <= types
    assert {"analysis.AnalysisResult", "partner.Critique"} <= types
    assert all(e["actor"] == "seed" or e["actor"].startswith("ai:") for e in audit)
    assert client.get("/api/eln/experiments/999/audit").status_code == 404


def test_addendum_validation(client: TestClient) -> None:
    blank = client.post("/api/eln/experiments/7/addenda", json={"note": "   "})
    assert blank.status_code == 400
    missing = client.post("/api/eln/experiments/999/addenda", json={"note": "x"})
    assert missing.status_code == 404


# ------------------------------------------------------ templates, drafts


def test_protocol_templates_versions_and_reuse(client: TestClient) -> None:
    empty = client.get("/api/eln/projects/1/protocol-templates").json()
    assert empty == {"project_id": 1, "total": 0, "items": []}
    from_exp = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={"name": "GCB 정제", "source_experiment_id": 7, "description": "#024 기반"},
    )
    assert from_exp.status_code == 201
    tpl = from_exp.json()
    assert tpl["version"] == 1 and tpl["condition_block"]["extraction_time_min"] == 5
    v2 = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={
            "name": "GCB 정제",
            "raw_note_template": "목적:\n",
            "condition_block": {"extraction_time_min": 10},
        },
    ).json()
    assert v2["version"] == 2
    latest = client.get("/api/eln/projects/1/protocol-templates").json()
    assert [(t["name"], t["version"]) for t in latest["items"]] == [("GCB 정제", 2)]
    every = client.get(
        "/api/eln/projects/1/protocol-templates", params={"all_versions": True}
    ).json()
    assert every["total"] == 2
    draft = client.get(
        "/api/eln/projects/1/experiment-draft", params={"protocol_template_id": v2["id"]}
    ).json()
    assert draft["source"] == "template" and draft["draft"]["raw_note"] == "목적:\n"
    assert draft["draft"]["protocol_template_id"] == v2["id"]
    created = client.post("/api/eln/projects/1/experiments", json=draft["draft"])
    assert created.status_code == 201 and created.json()["protocol_template_id"] == v2["id"]
    assert (
        client.post(
            "/api/eln/projects/1/protocol-templates", json={"name": "빈", "description": ""}
        ).status_code
        == 400
    )
    audit = client.get("/api/audit", params={"entity_type": "eln.ProtocolTemplate"}).json()
    assert len(audit) == 2


def test_clone_draft_and_create(client: TestClient) -> None:
    blank = client.get("/api/eln/projects/1/experiment-draft").json()
    assert blank["source"] == "blank" and blank["suggested_code"] == "#025"
    clone = client.get(
        "/api/eln/projects/1/experiment-draft", params={"source_experiment_id": 7}
    ).json()
    assert clone["source"] == "clone"
    body = clone["draft"]
    assert body["parent_experiment_id"] == 7 and body["cloned_from_experiment_id"] == 7
    assert body["condition_block"]["cleanup_sorbent"].startswith("PSA 50 mg + GCB")
    created = client.post("/api/eln/projects/1/experiments", json=body).json()
    assert created["code"] == "#025" and created["cloned_from_experiment_id"] == 7
    event = _audit(client, created["id"])[0]
    assert event["payload"]["cloned_from_experiment_id"] == 7
    both = client.get(
        "/api/eln/projects/1/experiment-draft",
        params={"source_experiment_id": 7, "protocol_template_id": 1},
    )
    assert both.status_code == 400
    assert (
        client.get(
            "/api/eln/projects/1/experiment-draft", params={"protocol_template_id": 999}
        ).status_code
        == 404
    )


# ------------------------------------------------------------ list filters


def test_list_pagination_and_filters(client: TestClient) -> None:
    url = "/api/eln/projects/1/experiments"
    page = client.get(url, params={"limit": 3, "offset": 2})
    assert [e["code"] for e in page.json()] == ["#020", "#021", "#022"]
    assert page.headers["x-total-count"] == "7"
    tail = client.get(url, params={"limit": 3, "offset": 6}).json()
    assert [e["code"] for e in tail] == ["#024"]
    assert client.get(url, params={"offset": 7}).json() == []
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"offset": -1}).status_code == 422
    me = client.get(url, params={"dataset_kind": "matrix_effect"})
    assert [e["code"] for e in me.json()] == ["#021"] and me.headers["x-total-count"] == "1"
    first = client.get(url).json()[0]
    same_day = client.get(
        url, params={"performed_from": first["performed_on"], "performed_to": first["performed_on"]}
    ).json()
    assert [e["code"] for e in same_day] == ["#018"]
    by_author = client.get(url, params={"author": first["author"]}).json()
    assert all(e["author"] == first["author"] for e in by_author) and by_author
    assert client.get(url, params={"author": "없는 사람"}).json() == []
