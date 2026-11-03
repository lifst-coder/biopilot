"""Engine protocol shared by the rules and Claude critique engines."""

from __future__ import annotations

from typing import Protocol

from app.partner.context import CritiqueContext
from app.partner.schemas import CritiqueDraft


class CritiqueEngine(Protocol):
    """Turns a grounded context into a :class:`CritiqueDraft` (or ``None`` to decline)."""

    name: str

    def critique(self, ctx: CritiqueContext) -> CritiqueDraft | None: ...
