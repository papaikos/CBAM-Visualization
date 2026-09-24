"""FastAPI application factory and static file serving."""

from __future__ import annotations

import mimetypes
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import config
from app.api import error_response, router, status_for
from app.errors import AppError

mimetypes.add_type("application/json", ".topojson")

# API data is served fresh on every request. Static files may be stored by the
# browser but must be revalidated (ETag / Last-Modified), so an unchanged file
# costs a 304 instead of a full download while a changed one is never stale.
API_CACHE_CONTROL = "no-store, max-age=0"
STATIC_CACHE_CONTROL = "no-cache"

# Already-compressed formats are not worth gzipping again.
GZIP_EXCLUDED_TYPES = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "application/gzip",
    config.XLSX_MIME,
)


class CacheControlMiddleware:
    """Set Cache-Control per response kind (plain ASGI, so file streaming is untouched)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_api = scope["path"] == "/api" or scope["path"].startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if is_api:
                    headers["Cache-Control"] = API_CACHE_CONTROL
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
                else:
                    headers["Cache-Control"] = STATIC_CACHE_CONTROL
            await send(message)

        await self.app(scope, receive, send_with_headers)


class PrecompressedStaticFiles(StaticFiles):
    """Serve ``<file>.gz`` with ``Content-Encoding: gzip`` when it exists and the client accepts gzip.

    Large assets (the country geometry) are compressed once at build time, so the
    server never spends CPU compressing them per request.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        request_headers = Headers(scope=scope)
        gzip_path = f"{full_path}.gz"
        if "gzip" in request_headers.get("accept-encoding", "") and os.path.isfile(gzip_path):
            media_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
            response = FileResponse(
                gzip_path,
                status_code=status_code,
                media_type=media_type,
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
                stat_result=os.stat(gzip_path),
            )
            if self.is_not_modified(response.headers, request_headers):
                return NotModifiedResponse(response.headers)
            return response
        return super().file_response(full_path, stat_result, scope, status_code)


def create_app() -> FastAPI:
    app = FastAPI(
        title="CBAM Visualization",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        GZipMiddleware,
        minimum_size=1024,
        compresslevel=6,
        exclude_content_types=GZIP_EXCLUDED_TYPES,
    )
    app.add_middleware(CacheControlMiddleware)
    app.include_router(router)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(status_for(exc), exc.code, str(exc))

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return error_response(400, "bad_request", str(exc))

    @app.exception_handler(LookupError)
    async def handle_lookup_error(request: Request, exc: LookupError) -> JSONResponse:
        return error_response(404, "not_found", str(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(400, "bad_request", str(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "internal_error", str(exc))

    if not config.PUBLIC_DIR.exists():
        raise FileNotFoundError(f"Public directory not found: {config.PUBLIC_DIR}")
    app.mount("/", PrecompressedStaticFiles(directory=config.PUBLIC_DIR, html=True), name="static")

    return app


app = create_app()
