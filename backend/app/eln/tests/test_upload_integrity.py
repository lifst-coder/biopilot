"""Regression tests for raw-upload integrity (multipart parsing and CSV header checks).

Each test pins a defect found in integration review of the former hand-rolled
``email``-based multipart parser, or of the lenient CSV header normalization:

1. a body without the closing ``--boundary--`` was accepted (truncated CSV stored);
2. a lone CR followed by the boundary string inside binary data cut the file short;
3. ``Content-Transfer-Encoding: base64`` parts were decoded, so stored ≠ sent bytes;
4. ``boundary=`` was matched case-sensitively; a 20 MB upload used ~263 MB of memory;
5. file names over 255 characters produced a 500 instead of a 400;
6. CSV headers with spaces (``"injection_id, level_ng_ml"``) were accepted although
   Analysis re-parses the stored text verbatim and then failed with a 500.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import tracemalloc
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.errors import ValidationFailedError
from app.eln import storage
from app.eln.multipart import read_form

BOUNDARY = "----BioPilotBoundary7MA4YWxk"
CAL = (
    "injection_id,level_ng_ml,analyte,analyte_area,is_area\n"
    "C1,1,azoxystrobin,100,1000\nC2,2,azoxystrobin,200,1000\n"
)


def _experiment(client: TestClient, code: str = "#950") -> int:
    body = {
        "code": code,
        "title": "업로드 무결성",
        "author": "박연구",
        "performed_on": "2026-11-01",
        "raw_note": "업로드 회귀 테스트",
        "condition_block": {"matrix": "사과", "sample_mass_g": 10},
    }
    response = client.post("/api/eln/projects/1/experiments", json=body)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _part(
    name: str,
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str = "application/octet-stream",
    extra_headers: tuple[str, ...] = (),
) -> bytes:
    """One encoded part including its leading delimiter and trailing CRLF."""
    disposition = f'form-data; name="{name}"'
    head = ""
    if filename is not None:
        disposition += f'; filename="{filename}"'
        head = f"Content-Type: {content_type}\r\n"
    head = f"Content-Disposition: {disposition}\r\n{head}"
    head += "".join(f"{h}\r\n" for h in extra_headers)
    return f"--{BOUNDARY}\r\n{head}\r\n".encode() + data + b"\r\n"


CLOSE = f"--{BOUNDARY}--\r\n".encode()


def _post(
    client: TestClient,
    url: str,
    body: bytes,
    content_type: str = f"multipart/form-data; boundary={BOUNDARY}",
) -> Any:
    return client.post(url, content=body, headers={"content-type": content_type})


def _events(client: TestClient, exp_id: int, entity_type: str) -> list[dict[str, Any]]:
    events = client.get(f"/api/eln/experiments/{exp_id}/audit").json()
    return [e for e in events if e["entity_type"] == entity_type]


# ------------------------------------------------- 1. truncated body (no close)


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(b"", id="no-closing-delimiter"),
        pytest.param(f"--{BOUNDARY}".encode(), id="delimiter-without-dashes"),
        pytest.param(f"--{BOUNDARY}\r\n".encode(), id="dangling-next-part"),
    ],
)
def test_body_without_closing_boundary_is_rejected(client: TestClient, tail: bytes) -> None:
    exp_id = _experiment(client)
    body = _part("kind", b"calibration") + _part("file", CAL.encode(), filename="c.csv") + tail
    response = _post(client, f"/api/eln/experiments/{exp_id}/datasets/upload", body)
    assert response.status_code == 400
    assert "잘렸습니다" in response.json()["message"]
    assert _events(client, exp_id, "eln.Dataset") == []


def test_body_cut_inside_file_is_rejected(client: TestClient) -> None:
    """A CSV cut mid-row is still valid CSV — only the missing delimiter reveals it."""
    exp_id = _experiment(client)
    cut = CAL.encode()[:-8]  # "...C2,2,azoxystrobin,2" — parses, but is not what was sent
    head = _part("kind", b"calibration") + _part("file", b"", filename="c.csv")[:-2]
    response = _post(client, f"/api/eln/experiments/{exp_id}/datasets/upload", head + cut)
    assert response.status_code == 400
    assert _events(client, exp_id, "eln.Dataset") == []
    complete = head + CAL.encode() + b"\r\n" + CLOSE
    ok = _post(client, f"/api/eln/experiments/{exp_id}/datasets/upload", complete)
    assert ok.status_code == 201, ok.text
    assert ok.json()["sha256"] == hashlib.sha256(CAL.encode()).hexdigest()


# ------------------------------------------ 2. lone CR before the boundary text


def test_lone_cr_before_boundary_text_keeps_binary_intact(client: TestClient) -> None:
    exp_id = _experiment(client)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + b"chunk\r--"
        + BOUNDARY.encode()
        + b"\r\nnot a part\x00\xff"
        + b"\r"
        + f"--{BOUNDARY}--".encode()
        + b"\rend"
    )
    body = _part("file", payload, filename="trace.bin") + CLOSE
    response = _post(client, f"/api/eln/experiments/{exp_id}/attachment-files", body)
    assert response.status_code == 201, response.text
    meta = response.json()
    assert meta["size_bytes"] == len(payload)
    assert meta["sha256"] == hashlib.sha256(payload).hexdigest()
    assert client.get(meta["download_url"]).content == payload


# ----------------------------------------- 3. Content-Transfer-Encoding: base64


def test_transfer_encoding_is_not_decoded_stored_bytes_equal_sent(client: TestClient) -> None:
    exp_id = _experiment(client)
    sent = base64.b64encode(b"\x00\x01binary payload\xff" * 8)
    body = (
        _part(
            "file",
            sent,
            filename="enc.bin",
            extra_headers=("Content-Transfer-Encoding: base64",),
        )
        + CLOSE
    )
    response = _post(client, f"/api/eln/experiments/{exp_id}/attachment-files", body)
    assert response.status_code == 201, response.text
    meta = response.json()
    assert meta["sha256"] == hashlib.sha256(sent).hexdigest()
    assert meta["size_bytes"] == len(sent)
    assert client.get(meta["download_url"]).content == sent


def test_transfer_encoding_on_csv_keeps_sent_text(client: TestClient) -> None:
    """A base64 CSV part is validated as the text that was sent (and so rejected)."""
    exp_id = _experiment(client)
    body = (
        _part("kind", b"calibration")
        + _part(
            "file",
            base64.b64encode(CAL.encode()),
            filename="c.csv",
            extra_headers=("Content-Transfer-Encoding: base64",),
        )
        + CLOSE
    )
    response = _post(client, f"/api/eln/experiments/{exp_id}/datasets/upload", body)
    assert response.status_code == 400
    assert "필수 컬럼 누락" in response.json()["message"]
    assert _events(client, exp_id, "eln.Dataset") == []


# ------------------------------- 4. case-insensitive boundary, memory, streaming


@pytest.mark.parametrize(
    "content_type",
    [
        f"multipart/form-data; Boundary={BOUNDARY}",
        f"multipart/form-data; BOUNDARY={BOUNDARY}",
        f'Multipart/Form-Data; boundary="{BOUNDARY}"',
    ],
)
def test_boundary_parameter_is_case_insensitive(client: TestClient, content_type: str) -> None:
    exp_id = _experiment(client)
    body = _part("kind", b"calibration") + _part("file", CAL.encode(), filename="c.csv") + CLOSE
    response = _post(client, f"/api/eln/experiments/{exp_id}/datasets/upload", body, content_type)
    assert response.status_code == 201, response.text
    assert response.json()["sha256"] == hashlib.sha256(CAL.encode()).hexdigest()


@pytest.mark.parametrize(
    "content_type",
    ["multipart/form-data", "multipart/form-data; boundary=", "text/plain; boundary=x"],
)
def test_missing_boundary_or_wrong_type_is_400(client: TestClient, content_type: str) -> None:
    exp_id = _experiment(client)
    body = _part("file", b"x", filename="a.bin") + CLOSE
    response = _post(client, f"/api/eln/experiments/{exp_id}/attachment-files", body, content_type)
    assert response.status_code == 400


def test_max_size_attachment_memory_is_bounded(client: TestClient) -> None:
    """A 20 MB upload must not balloon memory (old parser peaked at ~263 MB)."""
    exp_id = _experiment(client)
    size = storage.MAX_ATTACHMENT_BYTES
    payload = bytes(range(256)) * (size // 256)
    tracemalloc.start()
    try:
        response = client.post(
            f"/api/eln/experiments/{exp_id}/attachment-files",
            files={"file": ("big.bin", payload, "application/octet-stream")},
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert response.status_code == 201, response.text
    assert response.json()["sha256"] == hashlib.sha256(payload).hexdigest()
    # Measured ~3x (test client copy of the body + server read + hashing); old parser ~13x.
    assert peak < 5 * size, f"peak {peak / 2**20:.0f} MB for a {size / 2**20:.0f} MB upload"


def _streaming_request(chunks: list[bytes], content_type: str) -> tuple[Request, list[int]]:
    """A Request fed chunk by chunk with no Content-Length; records chunks consumed."""
    consumed: list[int] = []
    queue = list(chunks)

    async def receive() -> dict[str, Any]:
        body = queue.pop(0) if queue else b""
        consumed.append(len(body))
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-type", content_type.encode())],
    }
    return Request(scope, receive), consumed


def test_size_limit_is_enforced_while_streaming() -> None:
    """Over-limit bodies fail before the rest of the stream is read (no buffering)."""
    head = _part("file", b"", filename="big.bin")[:-2]
    chunks = [head] + [b"x" * (256 * 1024)] * 64  # 16 MB of file data
    request, consumed = _streaming_request(chunks, f"multipart/form-data; boundary={BOUNDARY}")
    with pytest.raises(ValidationFailedError, match="너무 큽니다"):
        asyncio.run(read_form(request, max_bytes=1024 * 1024))
    assert len(consumed) < 10  # stopped right after crossing 1 MB + overhead


def test_declared_content_length_over_limit_is_rejected_upfront(client: TestClient) -> None:
    exp_id = _experiment(client)
    response = client.post(
        f"/api/eln/experiments/{exp_id}/attachment-files",
        content=b"",
        headers={
            "content-type": f"multipart/form-data; boundary={BOUNDARY}",
            "content-length": str(storage.MAX_ATTACHMENT_BYTES * 2),
        },
    )
    assert response.status_code == 400 and "너무 큽니다" in response.json()["message"]


def test_duplicate_and_malformed_parts_are_400(client: TestClient) -> None:
    exp_id = _experiment(client)
    url = f"/api/eln/experiments/{exp_id}/datasets/upload"
    two_files = (
        _part("kind", b"calibration")
        + _part("file", CAL.encode(), filename="a.csv")
        + _part("file", CAL.encode(), filename="b.csv")
        + CLOSE
    )
    assert _post(client, url, two_files).status_code == 400
    no_name = f"--{BOUNDARY}\r\nContent-Disposition: form-data\r\n\r\nx\r\n".encode() + CLOSE
    assert _post(client, url, no_name).status_code == 400
    assert _events(client, exp_id, "eln.Dataset") == []


# --------------------------------------------------- 5. file name over 255 chars


@pytest.mark.parametrize(
    ("path", "fields"),
    [
        ("datasets/upload", {"kind": "calibration"}),
        ("datasets/import", {"kind": "calibration", "format": "wide_analyte_columns"}),
        ("attachment-files", {}),
    ],
)
def test_overlong_filename_is_400_not_500(
    client: TestClient, path: str, fields: dict[str, str]
) -> None:
    exp_id = _experiment(client)
    response = client.post(
        f"/api/eln/experiments/{exp_id}/{path}",
        files={"file": ("a" * 252 + ".csv", CAL.encode(), "text/csv")},
        data=fields,
    )
    assert response.status_code == 400
    assert "파일 이름이 너무 깁니다" in response.json()["message"]


def test_filename_of_255_chars_is_accepted_and_import_name_fits(client: TestClient) -> None:
    exp_id = _experiment(client)
    name = "a" * 251 + ".csv"
    upload = client.post(
        f"/api/eln/experiments/{exp_id}/datasets/upload",
        files={"file": (name, CAL.encode(), "text/csv")},
        data={"kind": "calibration"},
    )
    assert upload.status_code == 201 and upload.json()["filename"] == name
    wide = b"Injection,Level,azoxystrobin,IS Area\nCAL-01,1,1520,51000\nCAL-02,2,3010,50500\n"
    imported = client.post(
        f"/api/eln/experiments/{exp_id}/datasets/import",
        files={"file": (name, wide, "text/csv")},
        data={"kind": "calibration", "format": "wide_analyte_columns"},
    )
    assert imported.status_code == 201, imported.text
    assert len(imported.json()["filename"]) <= 255
    assert imported.json()["filename"].endswith(".long.csv")


# ------------------------------------------------ 6. spaced CSV headers rejected


SPACED = (
    "injection_id, level_ng_ml, analyte, analyte_area, is_area\n"
    "C1, 1, azoxystrobin, 100, 1000\nC2, 2, azoxystrobin, 200, 1000\n"
)


def test_csv_header_with_spaces_is_rejected_like_main(client: TestClient) -> None:
    exp_id = _experiment(client)
    upload = client.post(
        f"/api/eln/experiments/{exp_id}/datasets/upload",
        files={"file": ("spaced.csv", SPACED.encode(), "text/csv")},
        data={"kind": "calibration"},
    )
    assert upload.status_code == 400
    assert "필수 컬럼 누락" in upload.json()["message"]
    via_json = client.post(
        f"/api/eln/experiments/{exp_id}/datasets",
        json={"kind": "calibration", "filename": "spaced.csv", "content": SPACED},
    )
    assert via_json.status_code == 400
    dry_run = client.post(
        "/api/eln/datasets/validate",
        json={"kind": "calibration", "filename": "spaced.csv", "content": SPACED},
    ).json()
    assert dry_run["ok"] is False
    assert "missing_columns" in {i["code"] for i in dry_run["issues"]}
    assert _events(client, exp_id, "eln.Dataset") == []
    # Analysis on the experiment therefore never sees the spaced CSV (was a 500).
    run = client.post(f"/api/analysis/experiments/{exp_id}/run")
    assert run.status_code != 500
