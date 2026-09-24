"""HTTP API routes and the JSON error contract.

Every error response has the shape ``{"error": <code>, "message": <text>}``.
Domain exceptions (:mod:`app.errors`) carry their own code; the exception
handlers registered in :mod:`app.main` map them onto HTTP status codes.
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from typing import Any, Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app import config
from app import db
from app.db import connection, database_exists
from app.errors import (
    AppError,
    BadRequest,
    DatabaseUnavailable,
    InvalidJson,
    NotFound,
    PayloadTooLarge,
    UnsupportedYear,
    WorkbookFormatError,
    WorkbookTooLarge,
)
from app.services import batch, emissions

# app.services.excel (openpyxl) is imported inside the Excel routes: it is a large
# share of startup time and only those routes need it, so cold starts stay fast.

router = APIRouter(prefix="/api")

_STATUS_BY_ERROR = (
    (WorkbookTooLarge, 413),
    (PayloadTooLarge, 413),
    (WorkbookFormatError, 400),
    (BadRequest, 400),
    (NotFound, 404),
    (DatabaseUnavailable, 503),
)


def status_for(exc: AppError) -> int:
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status
    return 500


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _require_database() -> None:
    if not database_exists():
        raise DatabaseUnavailable(
            "The SQLite database is missing. Run `python scripts/import_csv.py` first.",
            code="database_not_ready",
        )


def _require_query(request: Request, key: str) -> str:
    value = (request.query_params.get(key) or "").strip()
    if not value:
        raise BadRequest(f"Missing required query parameter: {key}")
    return value


def _require_year(request: Request) -> int:
    raw = _require_query(request, "year")
    try:
        return int(raw)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc


async def _read_body(request: Request, maximum_bytes: int) -> bytes:
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        raise BadRequest("Content-Length is required.")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise BadRequest("Content-Length must be a non-negative integer.") from exc
    if length < 0:
        raise BadRequest("Content-Length must be a non-negative integer.")
    if length > maximum_bytes:
        if maximum_bytes == config.MAX_WORKBOOK_BYTES:
            raise WorkbookTooLarge("Request body exceeds the allowed size.")
        raise PayloadTooLarge("Request body exceeds the allowed size.")
    return await request.body()


def _content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip()


async def _read_json_payload(request: Request) -> dict:
    if _content_type(request) != "application/json":
        raise InvalidJson("Content-Type must be application/json.")
    body = await _read_body(request, config.MAX_JSON_BYTES)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidJson("The request body is not valid JSON.") from exc


def _excel():
    from app.services import excel

    return excel


def _encode_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# Read-only queries whose results depend only on their arguments and the database file.
_CACHEABLE_QUERIES: dict[str, Callable[..., Any]] = {
    "meta": lambda: emissions.get_meta(),
    "map-data": lambda cn_code, year: emissions.get_map_data(cn_code, year),
    "country": lambda cn_code, year, country: emissions.get_country_detail(cn_code, year, country),
    "batch-meta": lambda: batch.get_batch_meta(),
    "batch-template": lambda: _excel().build_input_template(batch.get_batch_meta()),
}


@lru_cache(maxsize=1024)
def _cached_result(fingerprint: tuple, query: str, args: tuple) -> Any:
    """Memoize a query per database fingerprint; errors are raised, never cached."""
    result = _CACHEABLE_QUERIES[query](*args)
    return result if isinstance(result, bytes) else _encode_json(result)


def _cached(query: str, *args: Any) -> bytes:
    _require_database()
    return _cached_result(db.fingerprint(), query, args)


def _cached_json_response(query: str, *args: Any) -> Response:
    return Response(content=_cached(query, *args), media_type="application/json")


def _xlsx_response(workbook: bytes, filename: str) -> Response:
    return Response(
        content=workbook,
        media_type=config.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/health")
def health() -> JSONResponse:
    if not database_exists():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "database_not_ready",
                "message": f"Database file not found at {config.DB_PATH}",
            },
        )
    try:
        with connection() as conn:
            has_rows = conn.execute("SELECT 1 FROM emissions LIMIT 1").fetchone() is not None
    except sqlite3.Error as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "database_unavailable", "message": str(exc)},
        )
    return JSONResponse(content={"ok": True, "hasData": has_rows})


@router.get("/meta")
def meta() -> Response:
    return _cached_json_response("meta")


@router.get("/map-data")
def map_data(request: Request) -> Response:
    cn_code = _require_query(request, "cn_code")
    year = _require_year(request)
    return _cached_json_response("map-data", cn_code, year)


@router.get("/country")
def country_detail(request: Request) -> Response:
    cn_code = _require_query(request, "cn_code")
    year = _require_year(request)
    country = _require_query(request, "country")
    return _cached_json_response("country", cn_code, year, country)


@router.get("/batch-meta")
def batch_meta() -> Response:
    return _cached_json_response("batch-meta")


@router.get("/batch-template")
def batch_template() -> Response:
    return _xlsx_response(_cached("batch-template"), "CBAM_Batch_Input_Template.xlsx")


@router.post("/batch-import")
async def batch_import(request: Request) -> dict:
    if _content_type(request) != config.XLSX_MIME:
        raise WorkbookFormatError(
            "Upload a standard .xlsx workbook.", code="unsupported_workbook_type"
        )
    body = await _read_body(request, config.MAX_WORKBOOK_BYTES)
    return _excel().parse_input_workbook(body)


@router.post("/batch-report")
async def batch_report(request: Request) -> dict:
    payload = await _read_json_payload(request)
    return batch.build_batch_report(payload)


@router.post("/batch-export")
async def batch_export(request: Request) -> Response:
    payload = await _read_json_payload(request)
    report = batch.build_batch_report(payload)
    workbook = _excel().build_report_workbook(report)
    return _xlsx_response(workbook, f"CBAM_Batch_Report_{report['year']}.xlsx")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def unknown_api_path(path: str) -> JSONResponse:
    return error_response(404, "not_found", f"Unknown API path: /api/{path}")


__all__ = ["UnsupportedYear", "error_response", "router", "status_for"]
