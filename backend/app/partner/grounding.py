"""Grounding validator: every number in AI prose must trace to stored data (PAR-6).

A :class:`GroundingIndex` holds

* **evidence values** (with unit) — a prose number matches one when it equals the
  absolute value *after rounding to the number of decimals written* (``62`` and
  ``61.98`` both match ``61.976``; ``62.1`` does not), and when the units agree:
  ``%`` never matches a ``%p`` (percentage-point) value and vice versa;
* **free numbers** — digits that appear verbatim in evidence labels/texts, condition
  values, acceptance criteria and fixed statistical thresholds. These are
  unit-agnostic and must match exactly (numerically).

Prose tokens understood: plain and signed decimals, thousands separators
(``1,234.5``), scientific notation (``4.96e-21``, ``4.96×10^-21``), Korean native
numerals with a counter (``세 번``, ``다섯 개``) and unit suffixes (``%``, ``%p``,
``퍼센트``, ``퍼센트포인트``, ``pp``). Identifiers are not quantities: experiment codes
(``#024``), evidence/proposal keys (``E3``, ``P12``), chemical names (``MgSO4``,
``C18``) and weighting names (``1/x``, ``1/x2``, ``R²``) are ignored.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

Unit = str | None

#: Tokens that contain digits but are names, not quantities.
NAME_TOKENS: tuple[str, ...] = ("1/x2", "1/x²", "1/x", "R²", "r²", "2×2", "2x2")
#: Fixed statistical thresholds that may appear in prose.
STAT_THRESHOLDS: tuple[str, ...] = ("0.05", "0.01", "0.001")

#: Korean native numerals; "한"(1) is excluded on purpose: "한 번 더" is an idiom.
KOREAN_NUMERALS: dict[str, int] = {
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
KOREAN_COUNTERS: tuple[str, ...] = ("번", "개", "회", "가지", "종", "건", "차례", "배", "곳", "명")

_PCT_POINT = r"(?:\s?%\s?p(?:t)?|\s?%\s?포인트|\s?퍼센트\s?포인트|\s?pp(?![a-zA-Z]))"
_PCT = r"(?:\s?%|\s?퍼센트|\s?프로)"
_NUM = (
    r"(?<![#\w.])"
    r"(?P<sign>[-−+]?)"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<sci>\s?(?:[eE]|[×x*]\s?10\^?)\s?(?P<exp>[-−+]?\d+))?"
    rf"(?P<unit>{_PCT_POINT}|{_PCT})?"
)
_NUMBER_RE = re.compile(_NUM)
_KOREAN_RE = re.compile(
    r"(?<![가-힣])(?P<word>"
    + "|".join(sorted(KOREAN_NUMERALS, key=len, reverse=True))
    + r")\s?(?:"
    + "|".join(KOREAN_COUNTERS)
    + r")(?![가-힣])"
)
#: Identifiers that contain digits: injection/sample ids (``R10-3``, ``S-03``), ISO dates.
_IDENT_RE = re.compile(r"\b[A-Za-z]+\d*-\d+[A-Za-z]?\b|\b\d{4}-\d{2}-\d{2}\b")
_FREE_RE = re.compile(r"(?<![#\w.])[-−]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class NumberToken:
    """A quantity found in prose."""

    raw: str
    value: float
    decimals: int
    unit: Unit
    exponent: int | None = None
    alternatives: tuple[float, ...] = ()


def _unit(raw: str | None) -> Unit:
    if not raw:
        return None
    compact = raw.replace(" ", "").lower()
    if compact.startswith("%p") or "포인트" in compact or compact == "pp":
        return "%p"
    return "%"


def extract_numbers(text: str) -> list[NumberToken]:
    """Return quantity tokens in ``text`` (identifiers and name tokens excluded)."""
    for token in NAME_TOKENS:
        text = text.replace(token, " ")
    text = _IDENT_RE.sub(" ", text)
    tokens: list[NumberToken] = []
    for m in _NUMBER_RE.finditer(text):
        num = m.group("num")
        plain = num.replace(",", "")
        decimals = len(plain.split(".")[1]) if "." in plain else 0
        exponent = int(m.group("exp").replace("−", "-")) if m.group("sci") else None
        alternatives: tuple[float, ...] = ()
        if "," in num and "." not in num:
            # "70,120" may be a list rather than a thousands-separated number.
            alternatives = tuple(float(p) for p in num.split(","))
        tokens.append(
            NumberToken(
                raw=m.group(0).strip(),
                value=float(plain),
                decimals=decimals,
                unit=_unit(m.group("unit")),
                exponent=exponent,
                alternatives=alternatives,
            )
        )
    for m in _KOREAN_RE.finditer(text):
        tokens.append(
            NumberToken(
                raw=m.group(0), value=float(KOREAN_NUMERALS[m.group("word")]), decimals=0, unit=None
            )
        )
    return tokens


def free_numbers(text: str) -> set[float]:
    """Numbers appearing verbatim in a source text (labels, conditions, criteria)."""
    out: set[float] = set()
    for m in _FREE_RE.findall(text):
        out.add(abs(float(m.replace("−", "-"))))
    return out


@dataclass
class GroundingIndex:
    """Allowed values for one context. Build with :meth:`add_value` / :meth:`add_text`."""

    values: list[tuple[float, Unit]] = field(default_factory=list)
    free: set[float] = field(default_factory=set)

    def add_value(self, value: float | None, unit: Unit = None) -> None:
        if value is not None and math.isfinite(value):
            self.values.append((abs(value), unit if unit in ("%", "%p") else None))

    def add_text(self, text: str | None) -> None:
        if text:
            self.free |= free_numbers(text)

    def add_free(self, values: Iterable[float]) -> None:
        self.free |= {abs(v) for v in values}

    # ---------------------------------------------------------------- match

    def _matches_free(self, value: float) -> bool:
        return any(math.isclose(value, f, rel_tol=1e-9, abs_tol=1e-9) for f in self.free)

    def _matches_value(self, token: NumberToken, value: float) -> bool:
        tol = 0.5 * 10 ** (-token.decimals) + 1e-9
        for v, unit in self.values:
            if token.unit is not None and unit is not None and token.unit != unit:
                continue
            if token.exponent is not None:
                if v == 0:
                    continue
                if abs(v / 10**token.exponent - value) <= tol:
                    return True
            elif abs(v - value) <= tol:
                return True
        return False

    def is_grounded(self, token: NumberToken) -> bool:
        """True when the token traces to an evidence value or a free number."""
        if token.exponent is None and self._matches_free(token.value):
            return True
        if self._matches_value(token, token.value):
            return True
        if token.alternatives:
            return all(
                self._matches_free(a) or self._matches_value(token, a) for a in token.alternatives
            )
        return False

    def grounds(self, value: float, unit: Unit = None) -> bool:
        """True when a structured (non-prose) field equals an indexed value *exactly*.

        Structured numbers (e.g. a design's replicate count) are copied, not rounded,
        so no rounding tolerance applies.
        """
        v = abs(value)
        if self._matches_free(v):
            return True
        return any(
            math.isclose(v, ev, rel_tol=1e-9, abs_tol=1e-9)
            for ev, ev_unit in self.values
            if unit is None or ev_unit is None or ev_unit == unit
        )

    def ungrounded(self, texts: Iterable[str]) -> list[str]:
        """Raw tokens (in order) that do not trace to the index."""
        return [t.raw for text in texts for t in extract_numbers(text) if not self.is_grounded(t)]


def base_index() -> GroundingIndex:
    """Index pre-filled with fixed statistical thresholds."""
    index = GroundingIndex()
    index.add_free(float(t) for t in STAT_THRESHOLDS)
    return index
