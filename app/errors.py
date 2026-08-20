"""Domain exceptions shared across the service and API layers.

Each exception carries a stable machine-readable ``code`` that the API layer
translates into the JSON error contract ``{"error": code, "message": ...}``.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for errors with a stable API error code."""

    code = "internal_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class BadRequest(AppError, ValueError):
    code = "bad_request"


class InvalidJson(BadRequest):
    code = "invalid_json"


class UnsupportedYear(BadRequest):
    code = "unsupported_year"


class NotFound(AppError, LookupError):
    code = "not_found"


class PayloadTooLarge(AppError):
    code = "payload_too_large"


class DatabaseUnavailable(AppError):
    code = "source_rows_unavailable"


class WorkbookFormatError(AppError, ValueError):
    code = "invalid_workbook"


class WorkbookTooLarge(WorkbookFormatError):
    code = "workbook_too_large"
