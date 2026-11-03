"""``multipart/form-data`` reading for ELN uploads, built on ``python-multipart``.

Parsing is delegated to Starlette's streaming :class:`~starlette.formparsers.MultiPartParser`
(the same parser behind FastAPI's ``UploadFile``/``Form``); file parts arrive as
:class:`~starlette.datastructures.UploadFile` objects spooled to disk past 1 MB. ELN wraps
it because raw-record integrity needs guarantees the stock ``Form``/``File`` parameters do
not give:

* **size limit while streaming** — the request body is counted chunk by chunk and the
  upload is rejected as soon as it exceeds the limit, before the rest is read;
* **complete bodies only** — ``python-multipart`` accepts a body that stops before the
  closing ``--boundary--`` delimiter, which would let a truncated CSV be stored as an
  immutable original. We require the parser to have reached the end state;
* **bytes as sent** — no ``Content-Transfer-Encoding`` decoding (RFC 7578 §4.7 deprecates
  it); the stored original is exactly the part body the client transmitted;
* **400, never 500** — malformed forms, duplicate fields and file names longer than
  :data:`MAX_FILENAME_LENGTH` are reported as :class:`ValidationFailedError`.

The routes keep their ``Request`` signature so the documented OpenAPI contract
(``openapi_extra`` in the router) is unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass, field

from fastapi import Request
from python_multipart.multipart import parse_options_header
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.errors import ValidationFailedError
from app.eln.schemas import MAX_FILENAME_LENGTH

#: Body allowance on top of the file limit for headers, boundaries and text fields.
FORM_OVERHEAD_BYTES = 64 * 1024
#: Largest accepted text (non-file) field.
MAX_TEXT_FIELD_BYTES = 64 * 1024
#: Upper bounds on parts per request (ELN forms have one file and a few fields).
MAX_FILES = 4
MAX_FIELDS = 16


@dataclass
class FilePart:
    """One uploaded file, read fully into memory after the size check."""

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


class _CompletionTrackingParser(MultiPartParser):
    """Starlette's parser, plus a flag set when the closing delimiter has been seen.

    ``python-multipart`` emits its ``end`` callback only after ``--boundary--``;
    its ``finalize()`` does not verify that state, so we do.
    """

    completed: bool = False

    def on_end(self) -> None:
        """Called by ``python-multipart`` once the closing delimiter is parsed."""
        self.completed = True


def _too_big(max_bytes: int) -> ValidationFailedError:
    return ValidationFailedError(f"파일이 너무 큽니다 (최대 {max_bytes // (1024 * 1024)} MB)")


def _boundary_content_type(content_type: str) -> None:
    """Require ``multipart/form-data`` with a boundary (type and parameter names are
    case-insensitive per RFC 2045 §5.1)."""
    media_type, params = parse_options_header(content_type)
    if media_type != b"multipart/form-data" or not params.get(b"boundary"):
        raise ValidationFailedError("multipart/form-data 요청이어야 합니다")


async def _limited_stream(
    request: Request, limit: int, max_bytes: int
) -> AsyncGenerator[bytes, None]:
    """Yield the request body, failing as soon as more than ``limit`` bytes arrived."""
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise _too_big(max_bytes)
        yield chunk


async def _collect(items: list[tuple[str, str | UploadFile]], max_bytes: int) -> FormData:
    """Turn parser output into :class:`FormData`, validating each part."""
    form = FormData()
    seen: set[str] = set()
    for name, value in items:
        if name in seen:
            raise ValidationFailedError(f"form field '{name}' appears more than once")
        seen.add(name)
        if isinstance(value, str):
            form.fields[name] = value
            continue
        filename = value.filename or ""
        if len(filename) > MAX_FILENAME_LENGTH:
            raise ValidationFailedError(
                f"파일 이름이 너무 깁니다 ({len(filename)}자 > {MAX_FILENAME_LENGTH}자)"
            )
        if value.size is not None and value.size > max_bytes:
            raise _too_big(max_bytes)
        data = await value.read()
        form.files[name] = FilePart(
            filename=filename,
            content_type=value.content_type or "application/octet-stream",
            data=data,
        )
    return form


async def read_form(request: Request, max_bytes: int) -> FormData:
    """Parse a ``multipart/form-data`` request whose file parts are at most ``max_bytes``.

    Raises :class:`ValidationFailedError` (400) for a non-multipart request, a body over
    the limit (checked against ``Content-Length`` and again while streaming), a body
    without the closing delimiter, malformed parts, duplicate fields, oversized files and
    over-long file names. Spooled temporary files are always closed.
    """
    _boundary_content_type(request.headers.get("content-type", ""))
    limit = max_bytes + FORM_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_big(max_bytes)

    items: list[tuple[str, str | UploadFile]] = []
    try:
        async with aclosing(_limited_stream(request, limit, max_bytes)) as stream:
            parser = _CompletionTrackingParser(
                request.headers,
                stream,
                max_files=MAX_FILES,
                max_fields=MAX_FIELDS,
                max_part_size=MAX_TEXT_FIELD_BYTES,
            )
            items = list((await parser.parse()).multi_items())
        if not parser.completed:
            raise ValidationFailedError(
                "multipart 본문이 잘렸습니다 (닫는 경계 '--boundary--' 없음) — 다시 업로드하세요"
            )
        return await _collect(items, max_bytes)
    except MultiPartException as exc:
        raise ValidationFailedError(f"multipart 본문을 해석할 수 없습니다: {exc.message}") from exc
    finally:
        for _, value in items:
            if not isinstance(value, str):
                await value.close()
