"""Domain exceptions shared across modules, mapped to HTTP responses in ``app.main``."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """Requested entity does not exist."""

    status_code = 404
    code = "not_found"


class ImmutableRecordError(DomainError):
    """Attempt to modify or delete an immutable original record."""

    status_code = 409
    code = "immutable_record"


class ValidationFailedError(DomainError):
    """Input is syntactically valid but semantically unusable (e.g. bad CSV)."""

    status_code = 400
    code = "validation_failed"
