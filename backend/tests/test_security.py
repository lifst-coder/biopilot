"""Security review regressions for the app shell (``app/main.py``, ``app/core``).

CORS defaults, request-body limits (size, JSON depth, JSON text validity) and error
responses that never carry tracebacks, file paths or SQL. See ``SECURITY_REVIEW.md``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import Database
from app.core.limits import RequestLimitMiddleware, json_problem
from app.main import create_app

SECRET_BITS = ("Traceback", "/home/", ".py", "SELECT", "sqlite3", "UNIQUE constraint")


def _app(**settings: object) -> FastAPI:
    return create_app(
        Settings(auto_seed=False, anthropic_api_key=None, **settings),  # type: ignore[arg-type]
        Database("sqlite://"),
    )


@pytest.fixture
def bare() -> Iterator[TestClient]:
    with TestClient(_app(), raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------- CORS


def test_cors_default_allows_only_the_dev_origin(bare: TestClient) -> None:
    ok = bare.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "*" not in ok.headers["access-control-allow-methods"]
    assert "DELETE" not in ok.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in ok.headers
    evil = bare.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    denied = bare.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"},
    )
    assert denied.status_code == 400


def test_cors_origins_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIOPILOT_CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]
    monkeypatch.setenv("BIOPILOT_CORS_ORIGINS", '["https://c.example"]')
    assert Settings().cors_origins == ["https://c.example"]
    with TestClient(_app(cors_origins=["https://a.example"])) as c:
        r = c.get("/api/health", headers={"Origin": "https://a.example"})
        assert r.headers["access-control-allow-origin"] == "https://a.example"
        assert "x-total-count" in r.headers["access-control-expose-headers"].lower()
        r = c.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------- body limits


def test_declared_oversize_body_is_rejected_before_reading(bare: TestClient) -> None:
    r = bare.post(
        "/api/eln/projects",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(64 * 1024 * 1024)},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"


def test_chunked_json_body_is_cut_off_at_the_limit() -> None:
    """Driven at the ASGI level: TestClient would buffer the whole body before sending."""
    received = 0
    reached_app = False

    async def receive() -> dict[str, object]:
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"a" * (1024 * 1024), "more_body": True}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def app(_scope: object, _receive: object, _send: object) -> None:
        nonlocal reached_app
        reached_app = True

    mw = RequestLimitMiddleware(
        app, max_request_bytes=32 * 1024 * 1024, max_json_bytes=1024 * 1024, max_json_depth=8
    )
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],  # no Content-Length
    }
    asyncio.run(mw(scope, receive, send))
    assert sent[0]["status"] == 413
    assert received == 2  # stopped after the first chunk past 1 MiB, never read 64 MiB
    assert not reached_app


def test_non_json_streamed_body_has_a_total_limit() -> None:
    def body() -> Iterator[bytes]:
        for _ in range(8):
            yield b"x" * (1024 * 1024)

    with TestClient(_app(max_request_bytes=2 * 1024 * 1024)) as c:
        r = c.post(
            "/api/eln/datasets/validate-upload",
            content=body(),
            headers={"content-type": "multipart/form-data; boundary=zz"},
        )
    assert r.status_code in (400, 413)  # ELN's own 5 MB form limit or the outer cap
    assert r.json()["code"] in ("payload_too_large", "validation_failed")


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (b'{"name": ' + b"[" * 100_000 + b"]" * 100_000 + b"}", "중첩"),
        (b'{"name": "x", "c": ' + b'{"a": ' * 40 + b"1" + b"}" * 40 + b"}", "중첩"),
        (b'{"name": "\\ud800"}', "서로게이트"),
        (b'{"\\udfff": "x"}', "서로게이트"),
        (b'{"name": "\xff\xfe"}', "UTF-8"),
    ],
)
def test_hostile_json_is_a_400_not_a_500(bare: TestClient, body: bytes, fragment: str) -> None:
    r = bare.post("/api/eln/projects", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["code"] == "validation_failed"
    assert fragment in r.json()["message"]


def test_ordinary_json_still_reaches_the_route(bare: TestClient) -> None:
    r = bare.post("/api/eln/projects", json={"name": "정상 프로젝트", "description": "😀 쌍 OK"})
    assert r.status_code == 201
    assert (
        bare.post(
            "/api/eln/projects", content=b"{bad", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )  # malformed JSON keeps FastAPI's own 422


def test_json_problem_checks() -> None:
    assert json_problem(b"", 4) is None
    assert json_problem(b'{"a": [1, {"b": "\\ud83d\\ude00"}]}', 4) is None  # valid pair
    assert json_problem(b"[[[[[1]]]]]", 4) is not None
    assert json_problem(b"[[[[1]]]]", 4) is None
    assert json_problem(b"not json", 4) is None  # left to FastAPI


# ----------------------------------------------------------- error leakage


def test_unhandled_errors_do_not_leak_internals() -> None:
    app = _app()

    def boom() -> None:
        raise RuntimeError("/home/user/biopilot/backend/app/x.py SELECT * FROM secrets")

    def conflict() -> None:
        raise IntegrityError(
            "INSERT INTO eln_experiment_revisions ...", {}, Exception("UNIQUE constraint failed")
        )

    app.add_api_route("/api/_boom", boom)
    app.add_api_route("/api/_conflict", conflict)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/_boom")
        assert r.status_code == 500
        assert r.json() == {"code": "internal_error", "message": "서버 내부 오류가 발생했습니다"}
        r2 = c.get("/api/_conflict")
        assert r2.status_code == 409 and r2.json()["code"] == "conflict"
        for resp in (r, r2):
            assert not any(bit in resp.text for bit in SECRET_BITS)


def test_validation_errors_do_not_echo_huge_inputs(bare: TestClient) -> None:
    r = bare.post("/api/eln/projects", json={"name": "x" * 1_000_000, "description": 1})
    assert r.status_code == 422
    assert len(r.content) < 5_000
    for err in r.json()["detail"]:
        assert set(err) >= {"loc", "msg", "type"}


def test_not_found_and_domain_errors_use_the_envelope(bare: TestClient) -> None:
    r = bare.get("/api/eln/experiments/999999")
    assert r.status_code == 404
    assert set(r.json()) == {"code", "message"}
    assert not any(bit in r.text for bit in SECRET_BITS)


def test_api_responses_carry_security_headers(bare: TestClient) -> None:
    r = bare.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert (
        bare.post(
            "/api/eln/projects", content=b"[" * 100, headers={"content-type": "application/json"}
        ).headers["x-content-type-options"]
        == "nosniff"
    )
    assert "content-security-policy" not in bare.get("/docs").headers  # Swagger UI uses a CDN
