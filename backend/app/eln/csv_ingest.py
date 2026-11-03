"""CSV decoding, parsing and contract validation (pure functions, ELN-1/ELN-7).

Uploads are decoded (UTF-8 with/without BOM, then CP949), parsed with pandas and checked
against the ``kind@version`` spec from :data:`DATASET_KIND_REGISTRY`. Findings are
returned as structured :class:`CsvIssue` items so the UI can point at row/column.
"""

from __future__ import annotations

import io
import math
from typing import Any

import pandas as pd

from app.eln.schemas import CsvIssue, DatasetKindSpec, IssueLevel

#: Maximum accepted CSV upload size in bytes.
MAX_CSV_BYTES = 5 * 1024 * 1024
#: At most this many row-level issues are reported per column/check.
MAX_ROW_ISSUES = 5


class DecodeError(ValueError):
    """Raised when bytes are neither UTF-8 nor CP949 text."""


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Decode upload bytes; returns ``(text, encoding)``.

    UTF-8 (BOM stripped) is tried first, then CP949 (EUC-KR superset used by Korean
    Windows instrument software). NUL bytes mean binary content and are rejected.
    """
    if b"\x00" in raw:
        raise DecodeError(
            "이진 파일로 보입니다 (NUL 바이트 포함) — CSV 텍스트만 업로드할 수 있습니다"
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp949"), "cp949"
    except UnicodeDecodeError as exc:
        raise DecodeError("인코딩을 판별할 수 없습니다 (UTF-8 또는 CP949만 지원)") from exc


def parse_frame(content: str, *, lenient: bool = False) -> pd.DataFrame:
    """Parse CSV text; raises ``ValueError`` with a user-facing message.

    The default (strict) mode parses exactly like the Analysis layer re-reads stored
    content (``pd.read_csv`` with default options), so a CSV that validates here is the
    CSV Analysis will see. Header cells are **not** trimmed: ``" level_ng_ml"`` is a
    different column and fails the contract check instead of being stored as-is.

    ``lenient=True`` trims header cells and skips spaces after delimiters. It is only for
    vendor exports that are converted and re-serialized to the canonical long CSV (which
    is then validated strictly) — never for content that is stored verbatim.
    """
    try:
        frame = pd.read_csv(io.StringIO(content), skipinitialspace=lenient)
    except pd.errors.EmptyDataError as exc:
        raise ValueError("빈 파일입니다 (헤더 행 없음)") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"CSV를 해석할 수 없습니다: {exc}") from exc
    if lenient:
        frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def _clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    """First ``limit`` rows as JSON-safe dicts (NaN → ``None``)."""
    return [
        {str(k): _clean(v) for k, v in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def _row_issue(level: IssueLevel, code: str, message: str, row: int, column: str) -> CsvIssue:
    return CsvIssue(level=level, code=code, message=message, row=row, column=column)


def _cell(frame: pd.DataFrame, index: Any, column: str) -> str:
    """Cell value as display text (for messages)."""
    return str(frame.at[index, column])


def validate_frame(frame: pd.DataFrame, spec: DatasetKindSpec) -> list[CsvIssue]:
    """Check a parsed frame against a dataset-kind spec. Errors block storage."""
    issues: list[CsvIssue] = []
    if any(c.startswith("Unnamed:") for c in frame.columns):
        issues.append(
            CsvIssue(level="warning", code="unnamed_column", message="이름 없는 컬럼이 있습니다")
        )
    duplicated = sorted({c for c in frame.columns if list(frame.columns).count(c) > 1})
    if duplicated:
        issues.append(
            CsvIssue(
                level="error",
                code="duplicate_column",
                message=f"중복 컬럼: {', '.join(duplicated)}",
            )
        )
    missing = [c for c in spec.required_columns if c not in frame.columns]
    if missing:
        issues.append(
            CsvIssue(
                level="error",
                code="missing_columns",
                message=f"{spec.ref} 필수 컬럼 누락: {', '.join(missing)}",
            )
        )
    if frame.empty:
        issues.append(CsvIssue(level="error", code="no_rows", message="데이터 행이 없습니다"))
        return issues
    known = set(spec.required_columns) | set(spec.optional_columns)
    if spec.required_columns:
        extra = [c for c in frame.columns if c not in known]
        if extra:
            issues.append(
                CsvIssue(
                    level="warning",
                    code="extra_columns",
                    message=f"계약에 없는 컬럼은 보관만 됩니다: {', '.join(extra)}",
                )
            )
    for col in spec.required_columns:
        if col not in frame.columns:
            continue
        blank_rows = [int(i) + 1 for i in frame.index[frame[col].isna()][:MAX_ROW_ISSUES]]
        for row in blank_rows:
            issues.append(_row_issue("error", "blank_value", f"{col} 값이 비어 있음", row, col))
    for col in spec.numeric_columns:
        if col not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[col], errors="coerce")
        bad = frame.index[numeric.isna() & frame[col].notna()]
        for i in bad[:MAX_ROW_ISSUES]:
            issues.append(
                _row_issue(
                    "error",
                    "not_numeric",
                    f"{col} 숫자가 아님: '{_cell(frame, i, col)}'",
                    int(i) + 1,
                    col,
                )
            )
        if len(bad) > MAX_ROW_ISSUES:
            issues.append(
                CsvIssue(
                    level="error",
                    code="not_numeric",
                    message=f"{col}: 숫자가 아닌 값 {len(bad)}건 (처음 {MAX_ROW_ISSUES}건 표시)",
                    column=col,
                )
            )
        negative = frame.index[numeric < 0]
        for i in negative[:MAX_ROW_ISSUES]:
            issues.append(
                _row_issue("warning", "negative_value", f"{col} 음수 값", int(i) + 1, col)
            )
    for col, allowed in spec.enum_columns.items():
        if col not in frame.columns:
            continue
        # Exact match: Analysis compares these values verbatim (no trimming).
        values = frame[col].astype(str)
        bad = frame.index[~values.isin(allowed) & frame[col].notna()]
        for i in bad[:MAX_ROW_ISSUES]:
            issues.append(
                _row_issue(
                    "error",
                    "not_allowed",
                    f"{col} 값 '{_cell(frame, i, col)}' 허용 안 됨 ({'/'.join(allowed)})",
                    int(i) + 1,
                    col,
                )
            )
    if "injection_id" in frame.columns and "analyte" in frame.columns:
        dup = frame.duplicated(subset=["injection_id", "analyte"], keep="first")
        for i in frame.index[dup][:MAX_ROW_ISSUES]:
            issues.append(
                _row_issue(
                    "warning",
                    "duplicate_row",
                    f"injection_id·analyte 중복: {_cell(frame, i, 'injection_id')}",
                    int(i) + 1,
                    "injection_id",
                )
            )
    return issues


def error_summary(issues: list[CsvIssue]) -> str:
    """One-line message listing errors (used for the 400 response body)."""
    errors = [i for i in issues if i.level == "error"]
    parts = [f"{i.row}행 {i.message}" if i.row else i.message for i in errors[:5]]
    more = f" 외 {len(errors) - 5}건" if len(errors) > 5 else ""
    return "CSV 검증 실패: " + "; ".join(parts) + more
