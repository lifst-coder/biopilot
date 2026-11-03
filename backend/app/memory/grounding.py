"""Number grounding for Claude output in Memory (MEM-6, Q&A).

Same principle as Partner's ``ungrounded_numbers``: every number in generated prose
must appear in the source material (allowing rounding to the precision written).
Memory cannot import Partner, so this is a small self-contained implementation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
#: Citation keys like ``F3`` are references, not quantities.
_CITATION = re.compile(r"\[?\bF\d+\b\]?")


def numbers(text: str) -> list[str]:
    """Numeric tokens in ``text`` (decimal comma normalised to a point)."""
    return [m.replace(",", ".") for m in _NUMBER.findall(text)]


def _dec(token: str) -> Decimal | None:
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _places(token: str) -> int:
    return len(token.split(".", 1)[1]) if "." in token else 0


def ungrounded_numbers(text: str, sources: Iterable[str]) -> list[str]:
    """Numbers in ``text`` that do not occur in ``sources`` (exactly or rounded)."""
    pool = [d for s in sources for t in numbers(s) if (d := _dec(t)) is not None]
    bad: list[str] = []
    for token in numbers(_CITATION.sub(" ", text)):
        value = _dec(token)
        if value is None:
            bad.append(token)
            continue
        places = _places(token)
        quantum = Decimal(1).scaleb(-places)
        if not any(value == s or s.quantize(quantum) == value for s in pool):
            bad.append(token)
    return bad
