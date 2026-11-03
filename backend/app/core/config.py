"""Application settings loaded from environment variables (prefix ``BIOPILOT_``)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    force_rules_mode: bool = False
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

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
