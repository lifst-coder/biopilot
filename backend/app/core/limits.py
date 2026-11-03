"""Request-body guards applied to every route before FastAPI parses anything.

FastAPI reads a JSON body completely into memory and hands it to :func:`json.loads`
without any bound, so before this middleware a single 300 MB ``POST`` (with or without
``Content-Length``) cost ~2.7 GB of RSS, a lone ``\\udXXX`` escape turned into a 500
while the error response was being encoded, and a 500-level nested object in a
``condition_block`` was accepted and then crashed response serialisation.

:class:`RequestLimitMiddleware` is a pure ASGI middleware (no ``BaseHTTPMiddleware``
buffering) that enforces, per request:

* **total body size** (``max_request_bytes``) — rejected from ``Content-Length`` before
  reading, and again while streaming for chunked bodies → ``413 payload_too_large``;
* **JSON body size** (``max_json_bytes``) for ``application/json`` and ``+json`` bodies;
* **well-formed, bounded JSON** — UTF-8/16/32 text, nesting depth ≤ ``max_json_depth``,
  no unpaired UTF-16 surrogates in any string or key → ``400 validation_failed``.

Multipart uploads keep their own, tighter per-file limits in ``app/eln/multipart.py``;
the total cap here is only the outer bound for any route.

:class:`SecurityHeadersMiddleware` adds ``nosniff``/CSP/referrer headers to API responses.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _TooLarge(Exception):
    """Raised inside the wrapped ``receive`` when the streamed body passes the limit."""


def json_problem(body: bytes, max_depth: int) -> str | None:
    """Return a user-facing reason why ``body`` is unacceptable JSON, or ``None``.

    The body is parsed once with :func:`json.loads` (C decoder, so this costs a few
    milliseconds per MB) and walked iteratively — never recursively — to check the
    nesting depth and that every string and key is encodable as UTF-8.
    """
    if not body.strip():
        return None  # FastAPI reports a missing body itself (422)
    try:
        doc = json.loads(body)
    except RecursionError:
        return f"JSON 중첩이 너무 깊습니다 (최대 {max_depth}단계)"
    except UnicodeDecodeError:
        return "JSON 본문이 UTF-8 텍스트가 아닙니다"
    except ValueError:
        return None  # malformed JSON: FastAPI's own 422 json_invalid response is fine
    stack: list[tuple[Any, int]] = [(doc, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, str):
            if not _utf8_safe(node):
                return "JSON 문자열에 짝이 없는 UTF-16 서로게이트(\\uD800–\\uDFFF)가 있습니다"
            continue
        if isinstance(node, dict | list):
            if depth > max_depth:
                return f"JSON 중첩이 너무 깊습니다 (최대 {max_depth}단계)"
            if isinstance(node, dict):
                stack.extend((k, depth) for k in node)
                stack.extend((v, depth + 1) for v in node.values())
            else:
                stack.extend((v, depth + 1) for v in node)
    return None


def _utf8_safe(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_json(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


class RequestLimitMiddleware:
    """Bound request bodies (size, JSON depth, JSON text validity) for every route."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_bytes: int,
        max_json_bytes: int,
        max_json_depth: int,
    ) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.max_json_bytes = max_json_bytes
        self.max_json_depth = max_json_depth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] != "http" or scope.get("method", "GET") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        is_json = _is_json(headers.get("content-type", ""))
        limit = (
            min(self.max_json_bytes, self.max_request_bytes)
            if is_json
            else (self.max_request_bytes)
        )
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await _reject(send, 413, "payload_too_large", _too_large_message(limit))
            return
        if is_json:
            await self._json(scope, receive, send, limit)
        else:
            await self._streamed(scope, receive, send, limit)

    async def _json(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                await _reject(send, 413, "payload_too_large", _too_large_message(limit))
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        problem = json_problem(body, self.max_json_depth)
        if problem is not None:
            await _reject(send, 400, "validation_failed", problem)
            return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _streamed(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        total = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send, 413, "payload_too_large", _too_large_message(limit))


def _too_large_message(limit: int) -> str:
    return f"요청 본문이 너무 큽니다 (최대 {limit // (1024 * 1024)} MB)"


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    """Send the standard ``{code, message}`` error envelope and close the response."""
    body = json.dumps({"code": code, "message": message}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


#: Headers added to every ``/api`` response. The API serves JSON, CSV and user-supplied
#: attachments (always ``Content-Disposition: attachment``); none of it may be sniffed
#: into HTML, framed or allowed to load anything.
API_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)


class SecurityHeadersMiddleware:
    """Add :data:`API_SECURITY_HEADERS` to ``/api`` responses (``/docs`` keeps its CDN)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api"):
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in API_SECURITY_HEADERS if k not in present]
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, with_headers)
