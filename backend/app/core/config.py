"""Application settings loaded from environment variables (prefix ``BIOPILOT_``)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AIMode = Literal["rules", "claude"]
#: Seed scenario loaded into an empty database (see ``app/seed/SCENARIO.md``).
SeedProfileName = Literal["reference", "lab"]


class Settings(BaseSettings):
    """Runtime configuration.

    ``ANTHROPIC_API_KEY`` is read without prefix because it is the SDK's standard
    variable. When it is absent every AI feature runs in deterministic ``rules`` mode.
    """

    model_config = SettingsConfigDict(env_prefix="BIOPILOT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./biopilot.db"
    auto_seed: bool = True
    #: ``BIOPILOT_SEED_PROFILE``: ``reference`` (7 experiments, every module test assumes it)
    #: or ``lab`` (two projects, 42 experiments, six months of decisions — demo opt-in).
    seed_profile: SeedProfileName = "reference"
    #: ``BIOPILOT_CORS_ORIGINS``: exact origins allowed to call the API from a browser,
    #: comma-separated (``https://a.example,https://b.example``) or a JSON list. The default
    #: is only the Vite dev server; the dev proxy and same-origin deployments need none.
    #: ``*`` is honoured only when set explicitly (never with credentials).
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    #: Methods/headers the browser may use cross-origin: exactly what the SPA sends.
    cors_allow_methods: Annotated[list[str], NoDecode] = ["GET", "POST", "PATCH"]
    cors_allow_headers: Annotated[list[str], NoDecode] = ["Content-Type", "Accept"]
    #: Upper bound for any request body (attachments are ≤ 20 MB + form overhead).
    max_request_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    #: Upper bound for ``application/json`` bodies (CSV text datasets are ≤ 5 MB).
    max_json_bytes: int = Field(default=12 * 1024 * 1024, gt=0)
    #: Deepest accepted JSON nesting (the API's deepest request model needs < 8).
    max_json_depth: int = Field(default=32, ge=4)
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    force_rules_mode: bool = False
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    @field_validator("cors_origins", "cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept a JSON list or a comma-separated string from the environment."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip() for part in text.split(",") if part.strip()]
        return value

    @property
    def ai_mode(self) -> AIMode:
        """Return ``claude`` only when an API key is configured and not overridden."""
        if self.anthropic_api_key and not self.force_rules_mode:
            return "claude"
        return "rules"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
