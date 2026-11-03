"""core.llm streaming capability (PAR-9): ClaudeGateway.stream_text and the non-streaming path.

No network: the Anthropic client inside ``ClaudeGateway`` is replaced with a stub that
mimics the SDK streaming helper (``with client.beta.messages.stream(...) as s``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.llm import (
    ClaudeGateway,
    LLMStreamError,
    RulesOnlyGateway,
    StreamingLLMGateway,
)
from app.partner import service as partner
from app.partner.schemas import AskRequest


class _Stream:
    def __init__(self, chunks: list[str], stop_reason: str) -> None:
        self.text_stream = iter(chunks)
        self._stop = stop_reason

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(stop_reason=self._stop)


class _StubClient:
    def __init__(
        self, chunks: list[str], stop_reason: str = "end_turn", error: Exception | None = None
    ):
        self.calls: list[dict[str, Any]] = []

        def stream(**kwargs: Any) -> _Stream:
            self.calls.append(kwargs)
            if error is not None:
                raise error
            return _Stream(chunks, stop_reason)

        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=stream))


def _gateway(client: _StubClient) -> ClaudeGateway:
    gw = ClaudeGateway(Settings(anthropic_api_key="test-key"))
    gw._client = client  # type: ignore[assignment]
    return gw


def test_claude_gateway_streams_text_chunks() -> None:
    client = _StubClient(["IS ", "억제 ", "[E1]"])
    gw = _gateway(client)
    assert isinstance(gw, StreamingLLMGateway)
    assert list(gw.stream_text(system="sys", prompt="질문")) == ["IS ", "억제 ", "[E1]"]
    (call,) = client.calls
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "질문"}]
    assert call["output_config"] == {"effort": Settings().claude_effort}
    assert call["fallbacks"] == "default"


def test_claude_stream_refusal_raises_after_chunks() -> None:
    gw = _gateway(_StubClient(["부분"], stop_reason="refusal"))
    seen: list[str] = []
    with pytest.raises(LLMStreamError, match="declined"):
        for chunk in gw.stream_text(system="s", prompt="p"):
            seen.append(chunk)
    assert seen == ["부분"]


def test_claude_stream_api_error_raises() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(request=request)
    gw = _gateway(_StubClient([], error=err))
    with pytest.raises(LLMStreamError, match="unreachable"):
        list(gw.stream_text(system="s", prompt="p"))


def test_rules_gateway_has_no_streaming_capability() -> None:
    assert not isinstance(RulesOnlyGateway(), StreamingLLMGateway)


class _NonStreamingClaude:
    """Claude-mode gateway without ``stream_text``: ask_stream must answer non-streaming."""

    mode = "claude"
    model_name = "fake-blocking"

    def generate(self, *, system: str, prompt: str, schema: type) -> None:
        return None  # → rules answer


def test_ask_stream_without_streaming_gateway_sends_blocking_answer(
    session: Session, seeded: dict[str, int]
) -> None:
    gw = _NonStreamingClaude()
    assert not isinstance(gw, StreamingLLMGateway)
    req = AskRequest(
        project_id=seeded["project"], experiment_id=seeded["#024"], question="IS 억제?"
    )
    events: list[tuple[str, dict[str, Any]]] = []
    for block in "".join(partner.ask_stream(session, req, gateway=gw)).strip().split("\n\n"):  # type: ignore[arg-type]
        head, data = block.split("\n", 1)
        events.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    names = [n for n, _ in events]
    assert names[0] == "start" and names[-1] == "final"
    assert events[0][1]["engine_candidate"] == "claude"
    assert "replace" not in names
    assert all(d["provisional"] is False for n, d in events if n == "delta")
    final = events[-1][1]
    assert final["engine"] == "rules" and final["evidence"]


def test_partner_detects_core_claude_gateway_as_streaming() -> None:
    gw = ClaudeGateway(Settings(anthropic_api_key="test-key"))
    assert isinstance(gw, partner.StreamingGateway)
