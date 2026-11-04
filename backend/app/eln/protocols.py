"""Protocol helpers (pure functions, no database): paste extraction, steps, diffs, runs.

Extraction policy — **never guess**:

* A value is ``recognized`` only when it is written in the pasted text: a known label
  followed by a value (``추출 시간: 10분``, a TSV/Markdown table row) or a pattern that
  names the condition explicitly (``pH 5.5``, ``PSA 50 mg + MgSO4 150 mg``,
  ``C18 2.1×100 mm``). The value is copied from the text, numbers are not converted.
* Several different values for one key, a range (``pH 5–6``), or a unit that does not
  match the key's unit leave the key empty (``ambiguous``/``unrecognized``) with a note.
* Every key that was not found is returned as ``unrecognized`` with ``value=None``.

Claude mode (:func:`validate_claude_draft`) must quote the line each value came from;
a quote that is not in the text, a number that is not in its quote, or an unknown key
rejects the whole draft and the caller falls back to the rules result.

Runs are append-only entry lists folded into the current state by :func:`fold_run`;
nothing is computed beyond copying planned/actual values and comparing them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.grounding import ungrounded_numbers
from app.eln.conditions import condition_fields
from app.eln.schemas import (
    CONDITION_FIELD_LABELS,
    CONDITION_FIELD_UNITS,
    ConditionField,
    ConditionValueChange,
    ExtractedField,
    ExtractedStep,
    ExtractionReview,
    ExtractionReviewItem,
    ExtractionSnapshot,
    ProtocolStep,
    RunCondition,
    RunDeviation,
    RunStep,
    UnmatchedLine,
)

NUM = r"(\d+(?:\.\d+)?)"
_RANGE_AFTER = re.compile(r"^\s*(?:[-–~～]|to|→|->)\s*\d")
_RANGE_BEFORE = re.compile(r"\d\s*(?:[-–~～]|to|→|->)\s*$")
_HAS_DIGIT = re.compile(r"\d")

#: Words naming a sample matrix right before its mass (``사과 15 g``).
MATRIX_WORDS = r"사과|감귤|김치|된장|토마토|현미|배추|고추|apple|pear|tomato|rice"
SOLVENT = (
    r"(?:(?:\d+(?:\.\d+)?\s*%\s*)?(?:아세트산|포름산|acetic acid|formic acid)\s*(?:함유\s*)?)?"
    r"(?<![A-Za-z])(?:아세토니트릴|메탄올|에틸\s*아세테이트|acetonitrile|methanol|ethyl acetate"
    r"|MeCN|ACN|MeOH)"
    r"(?![A-Za-z])"
    r"(?:\s*[:/]\s*물|\s*:\s*water)?"
    r"(?:\s*\((?:\d+(?:\.\d+)?\s*%\s*)?(?:아세트산|포름산|acetic acid|formic acid)\))?"
)
SORBENT = r"(?:PSA|C18(?:EC)?|GCB|MgSO4|MgSO₄|Z-Sep\+?|EMR-Lipid|Florisil)"
#: Lines about the LC mobile phase or dilution never carry the extraction solvent.
_NOT_EXTRACTION = re.compile(
    r"이동상|mobile phase|gradient|그래디언트|세척|wash|희석|dilut|표준\s*용액|stock|조제", re.I
)
#: Words between "추출" and a duration that mean the duration is another operation.
_OTHER_OPERATION = re.compile(r"후|원심|수화|방치|정치|centrif|after|hydrat", re.I)
_UNIT_END = r"(?![A-Za-z])"

#: Label synonyms (normalised: lower case, no spaces, no parenthesised unit).
LABEL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "matrix": ("매트릭스", "시료", "시료종류", "matrix", "sample", "samplematrix"),
    "sample_mass_g": (
        "시료량",
        "시료무게",
        "시료질량",
        "samplemass",
        "sampleweight",
        "sampleamount",
    ),
    "extraction_solvent": ("추출용매", "용매", "extractionsolvent", "solvent"),
    "extraction_volume_ml": (
        "추출용매량",
        "용매량",
        "추출부피",
        "solventvolume",
        "extractionvolume",
    ),
    "extraction_time_min": ("추출시간", "extractiontime"),
    "ph": ("ph",),
    "buffer": ("완충염", "완충액", "완충", "buffer", "buffersalts", "분배염"),
    "cleanup_sorbent": (
        "정제흡착제",
        "흡착제",
        "d-spe",
        "dspe",
        "정제",
        "cleanup",
        "clean-up",
        "sorbent",
    ),
    "column": ("컬럼", "칼럼", "column", "분석컬럼"),
    "column_temp_c": (
        "컬럼온도",
        "칼럼온도",
        "columntemperature",
        "columntemp",
        "오븐온도",
        "oventemperature",
    ),
    "internal_standard": ("내부표준", "내부표준물질", "internalstandard", "istd", "is"),
    "calibration_weighting": ("검량선가중", "가중", "가중치", "weighting", "calibrationweighting"),
    "instrument": ("기기", "장비", "instrument", "분석기기"),
}

#: Accepted spellings of each key's unit (lower case). Another unit → not recognized.
UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "g": ("g", "그램"),
    "mL": ("ml", "밀리리터"),
    "min": ("min", "mins", "minute", "minutes", "분"),
    "°C": ("°c", "℃", "도", "c", "° c"),
}

_HEADING = re.compile(
    r"^\s*(목적|절차|방법|관찰|결과|비고|메모|purpose|procedure|method|observations?|results?|notes?)"
    r"\s*(?:[:：]\s*|$)",
    re.I,
)
_PROCEDURE_HEADING = re.compile(r"^\s*(절차|방법|procedure|method)\s*(?:[:：]\s*|$)", re.I)
_STOP_HEADING = re.compile(
    r"^\s*(관찰|결과|비고|메모|observations?|results?|notes?)\s*(?:[:：]\s*|$)", re.I
)
_STEP_NUMBER = re.compile(
    r"^\s*(?:(?:step|단계)\s*)?(?:\d{1,2}\s*[.)．:]|\d{1,2}\s*단계\s*[:.)]?|[①-⑳])\s+(.+)$", re.I
)
_BULLET = re.compile(r"^\s*(?:[-*•·]\s+)")
_KV_SPLIT = re.compile(r"\t|\s*\|\s*|\s*[:：=]\s*|\s{2,}")


def field_meta() -> dict[str, ConditionField]:
    """Known condition keys (label, unit, value type) in display order."""
    return {f.key: f for f in condition_fields()}


def _norm_label(label: str) -> str:
    label = re.sub(r"\([^)]*\)", "", label)
    return re.sub(r"\s+", "", label).strip().lower().rstrip(".:")


def _label_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for key, label in CONDITION_FIELD_LABELS.items():
        index[_norm_label(label)] = key
        index[_norm_label(key)] = key
    for key, synonyms in LABEL_SYNONYMS.items():
        for s in synonyms:
            index[_norm_label(s)] = key
    return index


_LABELS = _label_index()


# --------------------------------------------------------------- extraction


@dataclass
class _Hit:
    key: str
    value: str | float | None
    line: int
    quote: str
    problem: str = ""  # "range" | "unit:<u>" | "" (ok)


def _is_range(text: str, start: int, end: int) -> bool:
    """The number at ``text[start:end]`` is one end of a range (``35–40``, ``5.0~5.5``)."""
    return bool(_RANGE_AFTER.match(text[end:]) or _RANGE_BEFORE.search(text[:start]))


def _unit_ok(unit: str, found: str) -> bool:
    found = found.strip().lower()
    return not found or found in UNIT_ALIASES.get(unit, (unit.lower(),))


def _weighting(text: str) -> str | None:
    """``1/x2`` / ``1/x`` / ``none`` when written explicitly; several → ``None``."""
    found: set[str] = set()
    if re.search(r"1\s*/\s*x\s*(?:²|\^?\s*2)", text, re.I):
        found.add("1/x2")
    if re.search(r"1\s*/\s*x(?!\s*(?:²|\^|2))", text, re.I):
        found.add("1/x")
    if re.search(r"무가중|가중\s*없음|unweighted|no weighting|weighting\s*[:=]\s*none", text, re.I):
        found.add("none")
    return found.pop() if len(found) == 1 else None


def _strip_particle(word: str) -> str:
    return re.sub(r"(은|는|을|를|이|가|으로|로|와|과|의)$", "", word)


def _clean_text_value(value: str) -> str:
    return value.strip().strip("|").strip().rstrip(".,;")


def _kv_hit(key: str, value: str, line_no: int, quote: str) -> _Hit:
    """Value written after an explicit label (table row / ``label: value``)."""
    meta = field_meta()[key]
    value = _clean_text_value(value)
    if meta.value_type == "number":
        numbers = list(re.finditer(NUM, value))
        if len(numbers) != 1:
            return _Hit(key, None, line_no, quote, "range" if len(numbers) > 1 else "empty")
        m = numbers[0]
        unit = CONDITION_FIELD_UNITS.get(key)
        after = re.match(r"\s*([^\d\s,;|]*)", value[m.end() :])
        found_unit = after.group(1) if after else ""
        if unit and found_unit and not _unit_ok(unit, found_unit):
            return _Hit(key, None, line_no, quote, f"unit:{found_unit}")
        return _Hit(key, float(m.group(1)), line_no, quote)
    if meta.value_type == "choice":
        w = _weighting(value)
        return _Hit(key, w, line_no, quote, "" if w else "empty")
    if not value:
        return _Hit(key, None, line_no, quote, "empty")
    return _Hit(key, value, line_no, quote)


def _free_hits(line: str, line_no: int) -> list[_Hit]:
    """Pattern matches in a free-text line (only explicit, unambiguous phrasings)."""
    quote = line.strip()
    hits: list[_Hit] = []

    def num_hit(key: str, m: re.Match[str], group: int = 1) -> None:
        problem = "range" if _is_range(line, m.start(group), m.end(group)) else ""
        hits.append(_Hit(key, None if problem else float(m.group(group)), line_no, quote, problem))

    for m in re.finditer(
        rf"(?:시료|샘플|sample|{MATRIX_WORDS})[^\n\d]{{0,12}}?{NUM}\s*g{_UNIT_END}", line, re.I
    ):
        num_hit("sample_mass_g", m)
    for m in re.finditer(
        rf"({MATRIX_WORDS})(\s*\([^)]{{1,20}}\))?\s*(?:시료\s*)?{NUM}\s*g{_UNIT_END}", line
    ):
        hits.append(_Hit("matrix", (m.group(1) + (m.group(2) or "")).strip(), line_no, quote))
    if not _NOT_EXTRACTION.search(line):
        for m in re.finditer(SOLVENT, line, re.I):
            hits.append(_Hit("extraction_solvent", m.group(0).strip(), line_no, quote))
        for m in re.finditer(rf"(?:{SOLVENT})\s*{NUM}\s*mL{_UNIT_END}", line, re.I):
            num_hit("extraction_volume_ml", m)
        for m in re.finditer(rf"{NUM}\s*mL\s*(?:의\s*)?(?:{SOLVENT})", line, re.I):
            num_hit("extraction_volume_ml", m)
        for m in re.finditer(rf"추출\s*용매(?:량)?\s*{NUM}\s*mL{_UNIT_END}", line, re.I):
            num_hit("extraction_volume_ml", m)
    for m in re.finditer(
        rf"(?:추출|extract(?:ion)?)([^\n\d,;]{{0,10}}?){NUM}\s*(?:분|min){_UNIT_END}", line, re.I
    ):
        if not _OTHER_OPERATION.search(m.group(1)):
            num_hit("extraction_time_min", m, 2)
    for m in re.finditer(
        rf"{NUM}\s*(?:분|min)(?:간)?\s*(?:동안\s*)?(?:진탕\s*)?(?:추출|extract)", line, re.I
    ):
        num_hit("extraction_time_min", m)
    for m in re.finditer(rf"(?<![A-Za-z])pH\s*(?:[:=]\s*)?{NUM}", line):
        num_hit("ph", m)
    if re.search(r"완충|buffer|EN\s*15662|AOAC", line, re.I):
        for m in re.finditer(
            r"(?:시트레이트|구연산염|아세테이트|citrate|acetate)\s*(?:완충염|완충액|완충|buffer(?:\s*salts?)?)?"
            r"(?:\s*\((?:EN\s*15662|AOAC\s*2007\.01)\))?",
            line,
            re.I,
        ):
            hits.append(_Hit("buffer", m.group(0).strip(), line_no, quote))
    if not re.search(r"컬럼|칼럼|column", line, re.I):
        for m in re.finditer(
            rf"{SORBENT}\s*{NUM}\s*mg(?:\s*(?:\+|,|및|and)\s*{SORBENT}\s*{NUM}\s*mg)*", line, re.I
        ):
            hits.append(_Hit("cleanup_sorbent", m.group(0).strip(), line_no, quote))
    if re.search(r"컬럼|칼럼|column", line, re.I):
        for m in re.finditer(
            rf"(?:[A-Za-z][\w\-+]*(?:\s[A-Za-z][\w\-+]*)?\s+)?{NUM}\s*[×xX*]\s*{NUM}\s*mm"
            rf"(?:\s*,?\s*{NUM}\s*(?:µm|um|μm))?",
            line,
        ):
            hits.append(_Hit("column", m.group(0).strip(), line_no, quote))
    if re.search(r"컬럼|칼럼|column|오븐|oven", line, re.I):
        temps = list(re.finditer(rf"{NUM}\s*(?:°\s*C|℃)", line))
        if len(temps) == 1:
            num_hit("column_temp_c", temps[0])
        elif len(temps) > 1:
            hits.append(_Hit("column_temp_c", None, line_no, quote, "range"))
    for m in re.finditer(
        r"(?:내부\s*표준(?:물질)?|internal standard|ISTD)\s*(?:\(IS\))?\s*[:=]?\s*"
        r"([A-Za-z0-9가-힣][^\s,;:]*(?:\s*\([^)]*\))?)",
        line,
        re.I,
    ):
        word = _strip_particle(m.group(1).strip())
        if word and word not in {"첨가", "사용", "용액", "없음", "물질"}:
            hits.append(_Hit("internal_standard", word, line_no, quote))
    w = _weighting(line) if re.search(r"1\s*/\s*x|가중|weight", line, re.I) else None
    if w:
        hits.append(_Hit("calibration_weighting", w, line_no, quote))
    for m in re.finditer(
        r"(?:LC|GC|UPLC|UHPLC|HPLC)-?(?:MS/MS|MS|QTOF|Q-TOF|Orbitrap|UV|DAD|FLD)(?:\s*\([^)]{1,30}\))?",
        line,
    ):
        hits.append(_Hit("instrument", m.group(0).strip(), line_no, quote))
    return hits


def _strip_step_prefix(line: str) -> str:
    m = _STEP_NUMBER.match(line)
    if m:
        return m.group(1).strip()
    return _BULLET.sub("", line).strip()


def _scan(text: str) -> list[_Hit]:
    hits: list[_Hit] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or re.fullmatch(r"[\s|:\-–]+", line):
            continue  # blank line or Markdown table separator
        quote = line.strip()
        body = _strip_step_prefix(line)
        body = _HEADING.sub("", body, count=1) if _HEADING.match(body) else body
        parts = [p for p in _KV_SPLIT.split(body.strip().strip("|")) if p.strip()]
        key = _LABELS.get(_norm_label(parts[0])) if len(parts) >= 2 else None
        if key is not None:
            value = " ".join(parts[1:])
            inner = [h for h in _free_hits(value, i) if not h.problem]
            same = [h for h in inner if h.key == key]
            hit = _kv_hit(key, value, i, quote)
            if field_meta()[key].value_type == "text" and len({str(h.value) for h in same}) == 1:
                hit.value = same[0].value  # the condition's own phrase inside the cell
            hits.append(hit)
            hits.extend(h for h in inner if h.key != key)
        else:
            hits.extend(_free_hits(body, i))
        for h in hits:
            if h.line == i:
                h.quote = quote
    return hits


def _same(a: str | float | None, b: str | float | None) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _fields_from_hits(hits: Iterable[_Hit]) -> list[ExtractedField]:
    by_key: dict[str, list[_Hit]] = {}
    for h in hits:
        by_key.setdefault(h.key, []).append(h)
    out: list[ExtractedField] = []
    for key, meta in field_meta().items():
        base = {"key": key, "label": meta.label, "unit": meta.unit, "value_type": meta.value_type}
        found = by_key.get(key, [])
        good = [h for h in found if not h.problem]
        bad = [h for h in found if h.problem and h.problem != "empty"]
        values: list[str | float] = []
        for h in good:
            if h.value is not None and not any(_same(h.value, v) for v in values):
                values.append(h.value)
        if len(values) == 1 and not bad:
            first = next(h for h in good if _same(h.value, values[0]))
            out.append(
                ExtractedField(
                    **base,
                    value=values[0],
                    status="recognized",
                    source_text=first.quote,
                    line=first.line,
                )
            )
        elif len(values) > 1 or (values and bad):
            out.append(
                ExtractedField(
                    **base,
                    status="ambiguous",
                    candidates=[h.quote for h in found if h.problem != "empty"],
                    line=found[0].line,
                    source_text=found[0].quote,
                    note="서로 다른 값이 여러 개 적혀 있음 — 하나를 직접 입력하세요",
                )
            )
        elif bad:
            h = bad[0]
            note = (
                f"단위({h.problem[5:]})가 {meta.unit}와 다름 — 직접 입력하세요"
                if h.problem.startswith("unit:")
                else "범위나 여러 값으로 적혀 있음 — 직접 입력하세요"
            )
            out.append(
                ExtractedField(
                    **base,
                    status="ambiguous" if h.problem == "range" else "unrecognized",
                    source_text=h.quote,
                    line=h.line,
                    candidates=[h.quote],
                    note=note,
                )
            )
        else:
            out.append(ExtractedField(**base, status="unrecognized"))
    return out


def _is_table_row(line: str) -> bool:
    """TSV / Markdown table rows (and separators) are condition lists, not steps."""
    return "\t" in line or line.lstrip().startswith("|") or bool(re.fullmatch(r"[\s|:\-–]+", line))


def _step_lines(lines: Sequence[str]) -> list[tuple[int, str, list[str]]]:
    """``(line_no, title, detail_lines)``: numbered steps, else lines of the procedure section.

    Without numbered lines the procedure section (``절차:`` up to ``관찰:``) gives one step
    per line; without a procedure heading every line outside other sections does.
    """
    numbered: list[tuple[int, str, list[str]]] = []
    for i, line in enumerate(lines, start=1):
        m = _STEP_NUMBER.match(line)
        if m:
            numbered.append((i, m.group(1).strip(), []))
        elif numbered and _STOP_HEADING.match(line):
            break
        elif numbered and line.strip() and not _HEADING.match(line):
            numbered[-1][2].append(_BULLET.sub("", line).strip())
    if numbered:
        return numbered
    steps: list[tuple[int, str, list[str]]] = []
    has_procedure = any(_PROCEDURE_HEADING.match(line) for line in lines)
    in_section = not has_procedure
    for i, line in enumerate(lines, start=1):
        if _PROCEDURE_HEADING.match(line):
            in_section = True
            rest = _PROCEDURE_HEADING.sub("", line, count=1).strip()
            if rest:
                steps.append((i, _BULLET.sub("", rest), []))
            continue
        if _STOP_HEADING.match(line):
            in_section = False
            continue
        if _HEADING.match(line):  # purpose line: not a step, section unchanged
            if has_procedure:
                in_section = False
            continue
        if in_section and line.strip() and not _is_table_row(line):
            steps.append((i, _BULLET.sub("", line).strip(), []))
    return steps


def split_steps(text: str, fields: Sequence[ExtractedField]) -> list[ExtractedStep]:
    """Procedure steps of ``text`` with the recognized keys read from each step's lines."""
    lines = text.splitlines()
    raw = _step_lines(lines)
    out: list[ExtractedStep] = []
    for n, (line_no, title, detail) in enumerate(raw):
        end = raw[n + 1][0] if n + 1 < len(raw) else len(lines) + 1
        keys = [
            f.key
            for f in fields
            if f.status == "recognized" and f.line is not None and line_no <= f.line < end
        ]
        out.append(
            ExtractedStep(
                title=title[:200],
                detail="\n".join(detail)[:2000],
                condition_keys=keys,
                line=line_no,
            )
        )
    return out


def unmatched_lines(text: str, fields: Sequence[ExtractedField]) -> list[UnmatchedLine]:
    """Lines with numbers from which no condition value was read (shown, never filled)."""
    used = {f.line for f in fields if f.line is not None}
    out: list[UnmatchedLine] = []
    for i, line in enumerate(text.splitlines(), start=1):
        body = _strip_step_prefix(line)
        if i in used or not _HAS_DIGIT.search(body) or re.fullmatch(r"[\s|:\-–]+", line):
            continue
        out.append(UnmatchedLine(line=i, text=line.strip()[:300]))
    return out


def extract_rules(
    text: str,
) -> tuple[list[ExtractedField], list[ExtractedStep], list[UnmatchedLine]]:
    """Offline rules extraction (see module docstring)."""
    fields = _fields_from_hits(_scan(text))
    return fields, split_steps(text, fields), unmatched_lines(text, fields)


# ------------------------------------------------------------ Claude drafts


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _line_of(text: str, quote: str) -> int | None:
    q = _collapse(quote)
    for i, line in enumerate(text.splitlines(), start=1):
        if q and q in _collapse(line):
            return i
    return None


def validate_claude_draft(
    text: str, fields: Sequence[tuple[str, str, str]], steps: Sequence[tuple[str, str, list[str]]]
) -> tuple[list[ExtractedField], list[ExtractedStep]] | str:
    """Check a Claude draft against the pasted text; return fields/steps or a reason.

    ``fields`` are ``(key, value, source_text)``; ``steps`` ``(title, detail, keys)``.
    """
    meta = field_meta()
    flat = _collapse(text)
    found: dict[str, ExtractedField] = {}
    for key, value, quote in fields:
        if key not in meta:
            return f"unknown condition key {key!r}"
        if key in found:
            return f"duplicate key {key!r}"
        if not quote.strip() or _collapse(quote) not in flat:
            return f"{key}: quote not found in the pasted text"
        if ungrounded_numbers(value, [quote]):
            return f"{key}: number not in its quote"
        line = _line_of(text, quote)
        base = {
            "key": key,
            "label": meta[key].label,
            "unit": meta[key].unit,
            "value_type": meta[key].value_type,
        }
        parsed: str | float
        if meta[key].value_type == "number":
            nums = re.findall(NUM, value)
            if len(nums) != 1:
                return f"{key}: not a single number"
            parsed = float(nums[0])
        elif meta[key].value_type == "choice":
            if value not in meta[key].options or _weighting(quote) != value:
                return f"{key}: choice not written in its quote"
            parsed = value
        else:
            if _collapse(value).lower() not in _collapse(quote).lower():
                return f"{key}: value not copied from its quote"
            parsed = value.strip()
        found[key] = ExtractedField(
            **base, value=parsed, status="recognized", source_text=quote.strip(), line=line
        )
    out_fields = [
        found.get(k)
        or ExtractedField(
            key=k, label=m.label, unit=m.unit, value_type=m.value_type, status="unrecognized"
        )
        for k, m in meta.items()
    ]
    out_steps: list[ExtractedStep] = []
    for title, detail, keys in steps:
        if any(k not in found for k in keys):
            return "step names a key without a value"
        if ungrounded_numbers(f"{title} {detail}", [text]):
            return "step text has numbers not in the pasted text"
        out_steps.append(
            ExtractedStep(
                title=title[:200],
                detail=detail[:2000],
                condition_keys=list(keys),
                line=_line_of(text, title),
            )
        )
    return out_fields, out_steps


# --------------------------------------------------------------- review


def _confirmed_equal(candidate: Any, confirmed: Any) -> bool:
    if candidate is None or confirmed is None:
        return candidate is confirmed
    try:
        return float(candidate) == float(confirmed)
    except (TypeError, ValueError):
        return _collapse(str(candidate)) == _collapse(str(confirmed))


def review(snapshot: ExtractionSnapshot, confirmed: dict[str, Any]) -> ExtractionReview:
    """Compare reviewed candidates with the confirmed condition block (provenance)."""
    labels = {k: m.label for k, m in field_meta().items()}
    items: list[ExtractionReviewItem] = []
    seen: set[str] = set()
    for f in snapshot.fields:
        seen.add(f.key)
        value = confirmed.get(f.key)
        if f.status == "recognized" and f.value is not None:
            if value is None:
                outcome = "cleared"
            elif _confirmed_equal(f.value, value):
                outcome = "accepted"
            else:
                outcome = "edited"
        else:
            outcome = "added" if value is not None else "left_empty"
        items.append(
            ExtractionReviewItem(
                key=f.key,
                label=f.label,
                candidate=f.value,
                candidate_status=f.status,
                source_text=f.source_text,
                confirmed=value,
                outcome=outcome,
            )
        )
    for key, value in confirmed.items():
        if key not in seen and value is not None:
            items.append(
                ExtractionReviewItem(
                    key=key,
                    label=labels.get(key, key),
                    candidate_status="unrecognized",
                    confirmed=value,
                    outcome="added",
                )
            )
    return ExtractionReview(
        engine=snapshot.engine,
        model=snapshot.model,
        fallback_reason=snapshot.fallback_reason,
        items=items,
        accepted_count=sum(i.outcome == "accepted" for i in items),
        edited_count=sum(i.outcome == "edited" for i in items),
        added_count=sum(i.outcome == "added" for i in items),
    )


# ---------------------------------------------------------------- steps


def derive_steps(note: str, block: dict[str, Any]) -> list[ProtocolStep]:
    """Steps from a note's procedure lines, with the block keys read from each line."""
    _, steps, _ = extract_rules(note)
    return [
        ProtocolStep(
            title=s.title,
            detail=s.detail,
            condition_keys=[k for k in s.condition_keys if k in block],
        )
        for s in steps
    ]


def executable_steps(steps: Sequence[ProtocolStep], block: dict[str, Any]) -> list[ProtocolStep]:
    """Steps to follow; block keys no step names go to a first "조건 확인" step."""
    named = {k for s in steps for k in s.condition_keys}
    rest = [k for k in block if k not in named]
    if not rest:
        return list(steps)
    prep = ProtocolStep(
        title="준비 — 조건 확인", detail="단계에 연결되지 않은 조건", condition_keys=rest
    )
    return [prep, *steps]


# ---------------------------------------------------------------- diffs


def _label(key: str) -> tuple[str, str | None]:
    return CONDITION_FIELD_LABELS.get(key, key), CONDITION_FIELD_UNITS.get(key)


def values_equal(a: Any, b: Any) -> bool:
    """Equal as numbers when both are numeric, else as trimmed text."""
    if a is None or b is None:
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return float(a) == float(b)
    return _collapse(str(a)) == _collapse(str(b))


def condition_changes(before: dict[str, Any], after: dict[str, Any]) -> list[ConditionValueChange]:
    """Keys added, removed or changed from ``before`` to ``after`` (field order)."""
    order = list(CONDITION_FIELD_LABELS) + sorted(
        k for k in {*before, *after} if k not in CONDITION_FIELD_LABELS
    )
    out: list[ConditionValueChange] = []
    for key in order:
        if key not in before and key not in after:
            continue
        a, b = before.get(key), after.get(key)
        label, unit = _label(key)
        if a is None and b is not None:
            out.append(ConditionValueChange(key=key, label=label, unit=unit, kind="added", after=b))
        elif a is not None and b is None:
            out.append(
                ConditionValueChange(key=key, label=label, unit=unit, kind="removed", before=a)
            )
        elif not values_equal(a, b):
            out.append(
                ConditionValueChange(
                    key=key, label=label, unit=unit, kind="changed", before=a, after=b
                )
            )
    return out


# ----------------------------------------------------------------- runs


@dataclass(frozen=True)
class RunEntryView:
    """Minimal view of a stored run entry (decoupled from the ORM row)."""

    seq: int
    kind: str
    step_index: int
    key: str | None
    value: Any
    note: str
    created_at: datetime


@dataclass
class FoldedRun:
    steps: list[RunStep]
    deviations: list[RunDeviation]
    actual_block: dict[str, Any]


def parse_actual(key: str, value: str | float | None) -> str | float | None:
    """Actual value as stored: numbers for numeric keys (``ValueError`` if not one)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    meta = field_meta().get(key)
    if meta is not None and meta.value_type == "number":
        if isinstance(value, int | float):
            return float(value)
        nums = re.findall(r"-?\d+(?:\.\d+)?", value)
        if len(nums) != 1 or re.sub(r"-?\d+(?:\.\d+)?", "", value).strip() not in (
            "",
            meta.unit or "",
        ):
            raise ValueError(f"{meta.label}: 숫자 하나로 입력하세요")
        return float(nums[0])
    if meta is not None and meta.value_type == "choice" and str(value) not in meta.options:
        raise ValueError(f"{meta.label}: {', '.join(meta.options)} 중 하나")
    return str(value).strip()


def fold_run(
    steps: Sequence[ProtocolStep],
    block: dict[str, Any],
    entries: Sequence[RunEntryView],
    *,
    include_skipped: bool,
) -> FoldedRun:
    """Current run state from its entries (later entries win)."""
    meta = field_meta()
    done: dict[int, datetime | None] = {}
    actual: dict[str, tuple[Any, int, str]] = {}
    notes: dict[int, list[str]] = {}
    for e in sorted(entries, key=lambda x: x.seq):
        if e.kind == "check":
            done[e.step_index] = e.created_at
        elif e.kind == "uncheck":
            done.pop(e.step_index, None)
        elif e.kind == "actual" and e.key is not None:
            if e.value is None:
                actual.pop(e.key, None)
            else:
                actual[e.key] = (e.value, e.step_index, e.note)
        elif e.kind == "note" and e.note.strip():
            notes.setdefault(e.step_index, []).append(e.note.strip())
    run_steps: list[RunStep] = []
    deviations: list[RunDeviation] = []
    for i, s in enumerate(steps):
        conds: list[RunCondition] = []
        for key in s.condition_keys:
            label, unit = _label(key)
            planned = block.get(key)
            got = actual.get(key)
            act = got[0] if got else None
            deviated = got is not None and not values_equal(planned, act)
            conds.append(
                RunCondition(
                    key=key,
                    label=label,
                    unit=unit,
                    value_type=meta[key].value_type if key in meta else "text",
                    planned=planned,
                    actual=act,
                    deviated=deviated,
                    note=got[2] if got else "",
                )
            )
            if deviated:
                deviations.append(
                    RunDeviation(
                        step_index=i,
                        step_title=s.title,
                        kind="value",
                        key=key,
                        label=label,
                        unit=unit,
                        planned=planned,
                        actual=act,
                        note=got[2] if got else "",
                    )
                )
        for n in notes.get(i, []):
            deviations.append(RunDeviation(step_index=i, step_title=s.title, kind="note", note=n))
        run_steps.append(
            RunStep(
                index=i,
                title=s.title,
                detail=s.detail,
                done=i in done,
                done_at=done.get(i),
                conditions=conds,
                notes=notes.get(i, []),
            )
        )
        if include_skipped and i not in done:
            deviations.append(RunDeviation(step_index=i, step_title=s.title, kind="skipped"))
    deviations.sort(key=lambda d: d.step_index)
    actual_block = dict(block)
    for key, (value, _, _) in actual.items():
        actual_block[key] = value
    return FoldedRun(steps=run_steps, deviations=deviations, actual_block=actual_block)


def _fmt(value: Any, unit: str | None) -> str:
    if value is None:
        return "(없음)"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value} {unit}" if unit else str(value)


def deviation_line(d: RunDeviation) -> str:
    """One line of the "프로토콜과 다른 점" list (values copied, not computed)."""
    where = f"{d.step_index + 1}단계 {d.step_title.rstrip('.。 ')}"
    if d.kind == "value":
        text = f"{where}: {d.label} {_fmt(d.planned, d.unit)} → {_fmt(d.actual, d.unit)}"
        return f"{text} ({d.note})" if d.note else text
    if d.kind == "note":
        return f"{where}: {d.note}"
    return f"{where}: 완료 표시 없음"


def compose_note(
    *,
    protocol: str,
    steps: Sequence[RunStep],
    deviations: Sequence[RunDeviation],
    observations: str,
) -> str:
    """Raw note of an experiment created from a run: steps, differences, observations."""
    lines = [f"목적: {protocol} 수행", "절차:"]
    for s in steps:
        mark = "[x]" if s.done else "[ ]"
        lines.append(f"{s.index + 1}. {mark} {s.title}")
    lines.append("프로토콜과 다른 점:")
    if deviations:
        lines.extend(f"- {deviation_line(d)}" for d in deviations)
    else:
        lines.append("- 없음")
    lines.append("관찰:")
    obs = [o for o in observations.splitlines() if o.strip()]
    lines.extend(obs or ["- "])
    return "\n".join(lines)
