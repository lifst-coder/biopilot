"""LLM gateway shared by AI features (Memory digests, Partner critique/ask).

Contract:
* ``rules`` mode (default, no API key): :meth:`LLMGateway.generate` returns ``None``
  and callers use their deterministic rules engine.
* ``claude`` mode: Claude is asked for JSON matching a Pydantic schema. Any failure
  (network, refusal, schema mismatch) returns ``None`` so callers fall back to rules.
Both modes therefore always produce the *same output schema* at the call site.

Optional capability: :class:`StreamingLLMGateway` adds :meth:`stream_text` (plain-text
token streaming, PAR-9). ``ClaudeGateway`` implements it with the Messages API streaming
helper; ``RulesOnlyGateway`` does not, so callers detect it with ``isinstance`` and fall
back to a blocking answer. Unlike ``generate``, a stream that fails (network, API error,
refusal) *raises* :class:`LLMStreamError` — chunks may already have been shown, so the
caller must explicitly replace them with its rules answer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from app.core.config import AIMode, Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMGateway(Protocol):
    """Minimal interface the rest of the app depends on (easy to fake in tests)."""

    @property
    def mode(self) -> AIMode: ...

    @property
    def model_name(self) -> str | None: ...

    def generate(self, *, system: str, prompt: str, schema: type[T]) -> T | None: ...


@runtime_checkable
class StreamingLLMGateway(Protocol):
    """Gateway that can also stream plain text token by token (PAR-9)."""

    def stream_text(self, *, system: str, prompt: str) -> Iterator[str]: ...


class LLMStreamError(RuntimeError):
    """A text stream ended without a usable answer (API error, network, refusal)."""


class RulesOnlyGateway:
    """Gateway used when no API key is configured. Never calls the network."""

    @property
    def mode(self) -> AIMode:
        return "rules"

    @property
    def model_name(self) -> str | None:
        return None

    def generate(self, *, system: str, prompt: str, schema: type[T]) -> T | None:
        return None


class ClaudeGateway:
    """Gateway backed by the Anthropic Messages API with JSON structured output."""

    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @property
    def mode(self) -> AIMode:
        return "claude"

    @property
    def model_name(self) -> str | None:
        return self._settings.claude_model

    def generate(self, *, system: str, prompt: str, schema: type[T]) -> T | None:
        import anthropic

        try:
            response = self._client.beta.messages.create(
                model=self._settings.claude_model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": self._settings.claude_effort,
                    "format": {"type": "json_schema", "schema": _strict_schema(schema)},
                },
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            logger.warning("Claude rate-limited; falling back to rules mode")
            return None
        except anthropic.APIStatusError as exc:
            logger.warning("Claude API error %s; falling back to rules mode", exc.status_code)
            return None
        except anthropic.APIConnectionError:
            logger.warning("Claude unreachable; falling back to rules mode")
            return None
        if response.stop_reason == "refusal":
            logger.warning("Claude declined the request; falling back to rules mode")
            return None
        text = "".join(getattr(b, "text", "") for b in response.content if b.type == "text")
        try:
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError):
            logger.warning("Claude output did not match %s; falling back", schema.__name__)
            return None

    def stream_text(self, *, system: str, prompt: str) -> Iterator[str]:
        """Stream the answer's text deltas (Messages API streaming helper).

        Yields text chunks as they arrive. Raises :class:`LLMStreamError` when the request
        fails or Claude declines (``stop_reason == "refusal"``, also after a server-side
        fallback); the caller then replaces the provisional text with its rules answer.
        """
        import anthropic

        try:
            with self._client.beta.messages.stream(
                model=self._settings.claude_model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self._settings.claude_effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMStreamError(f"Claude API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMStreamError("Claude unreachable") from exc
        if final.stop_reason == "refusal":
            raise LLMStreamError("Claude declined the request")


def _strict_schema(schema: type[BaseModel]) -> dict[str, object]:
    """JSON schema with ``additionalProperties: false`` on every object (API requirement)."""
    raw = schema.model_json_schema()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(raw)
    return raw


_gateway_override: LLMGateway | None = None


def set_gateway_override(gateway: LLMGateway | None) -> None:
    """Install a gateway for tests (``None`` restores settings-based selection)."""
    global _gateway_override
    _gateway_override = gateway


def get_gateway() -> LLMGateway:
    """Return the gateway for the current settings (or the test override)."""
    if _gateway_override is not None:
        return _gateway_override
    settings = get_settings()
    if settings.ai_mode == "claude":
        return ClaudeGateway(settings)
    return RulesOnlyGateway()
