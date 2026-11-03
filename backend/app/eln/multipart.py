"""Minimal ``multipart/form-data`` reader built on the standard ``email`` parser.

FastAPI's ``UploadFile``/``Form`` require the optional ``python-multipart`` package,
which is not a project dependency (shared ``pyproject.toml`` — requested in
CHANGES_REQUESTED.md). Until then ELN parses uploads itself. Size limits are enforced
before parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import Message
from email.parser import BytesParser
from email.policy import HTTP

from fastapi import Request

from app.core.errors import ValidationFailedError


@dataclass
class FilePart:
    """One uploaded file."""

    filename: str
    content_type: str
    data: bytes


@dataclass
class FormData:
    """Parsed form: text fields and files keyed by field name."""

    fields: dict[str, str] = field(default_factory=dict)
    files: dict[str, FilePart] = field(default_factory=dict)

    def text(self, name: str, default: str | None = None) -> str:
        """Text field value; raises 400 when missing and no default is given."""
        if name in self.fields:
            return self.fields[name]
        if default is None:
            raise ValidationFailedError(f"form field '{name}' is required")
        return default

    def file(self, name: str = "file") -> FilePart:
        """File part; raises 400 when missing."""
        if name not in self.files:
            raise ValidationFailedError(f"file field '{name}' is required")
        return self.files[name]


def parse_multipart(content_type: str, body: bytes) -> FormData:
    """Parse a multipart body. Raises :class:`ValidationFailedError` on bad input."""
    is_form = content_type.lower().startswith("multipart/form-data")
    if not is_form or "boundary=" not in content_type:
        raise ValidationFailedError("multipart/form-data 요청이어야 합니다")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    message = BytesParser(policy=HTTP).parsebytes(header + body)
    if not message.is_multipart():
        raise ValidationFailedError("multipart 본문을 해석할 수 없습니다")
    form = FormData()
    parts = message.get_payload()
    assert isinstance(parts, list)
    for part in parts:
        if not isinstance(part, Message):  # pragma: no cover - defensive
            continue
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else b""
        filename = part.get_filename()
        if filename is not None:
            form.files[name] = FilePart(
                filename=filename,
                content_type=part.get_content_type(),
                data=data,
            )
        else:
            charset = part.get_content_charset() or "utf-8"
            form.fields[name] = data.decode(charset, errors="replace")
    return form


async def read_form(request: Request, max_bytes: int) -> FormData:
    """Read and parse the request body, rejecting bodies larger than ``max_bytes`` (+form)."""
    limit = max_bytes + 64 * 1024  # allowance for headers/boundaries/text fields
    too_big = f"파일이 너무 큽니다 (최대 {max_bytes // (1024 * 1024)} MB)"
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ValidationFailedError(too_big)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise ValidationFailedError(too_big)
        chunks.append(chunk)
    return parse_multipart(request.headers.get("content-type", ""), b"".join(chunks))
