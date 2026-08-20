"""HTTP API routes and the JSON error contract.

Every error response has the shape ``{"error": <code>, "message": <text>}``.
Domain exceptions (:mod:`app.errors`) carry their own code; the exception
handlers registered in :mod:`app.main` map them onto HTTP status codes.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app import config
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
from app.services.excel import (
    MAX_WORKBOOK_BYTES,
    build_input_template,
    build_report_workbook,
    parse_input_workbook,
)

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
        if maximum_bytes == MAX_WORKBOOK_BYTES:
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
def meta() -> dict:
    _require_database()
    return emissions.get_meta()


@router.get("/map-data")
def map_data(request: Request) -> dict:
    _require_database()
    cn_code = _require_query(request, "cn_code")
    year = _require_year(request)
    return emissions.get_map_data(cn_code, year)


@router.get("/country")
def country_detail(request: Request) -> dict:
    _require_database()
    cn_code = _require_query(request, "cn_code")
    year = _require_year(request)
    country = _require_query(request, "country")
    return emissions.get_country_detail(cn_code, year, country)


@router.get("/batch-meta")
def batch_meta() -> dict:
    _require_database()
    return batch.get_batch_meta()


@router.get("/batch-template")
def batch_template() -> Response:
    _require_database()
    workbook = build_input_template(batch.get_batch_meta())
    return _xlsx_response(workbook, "CBAM_Batch_Input_Template.xlsx")


@router.post("/batch-import")
async def batch_import(request: Request) -> dict:
    if _content_type(request) != config.XLSX_MIME:
        raise WorkbookFormatError(
            "Upload a standard .xlsx workbook.", code="unsupported_workbook_type"
        )
    body = await _read_body(request, MAX_WORKBOOK_BYTES)
    return parse_input_workbook(body)


@router.post("/batch-report")
async def batch_report(request: Request) -> dict:
    payload = await _read_json_payload(request)
    return batch.build_batch_report(payload)


@router.post("/batch-export")
async def batch_export(request: Request) -> Response:
    payload = await _read_json_payload(request)
    report = batch.build_batch_report(payload)
    workbook = build_report_workbook(report)
    return _xlsx_response(workbook, f"CBAM_Batch_Report_{report['year']}.xlsx")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def unknown_api_path(path: str) -> JSONResponse:
    return error_response(404, "not_found", f"Unknown API path: /api/{path}")


__all__ = ["UnsupportedYear", "error_response", "router", "status_for"]
