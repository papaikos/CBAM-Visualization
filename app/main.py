"""FastAPI application factory and static file serving."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app import config
from app.api import error_response, router, status_for
from app.errors import AppError


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable caching on every response, matching the app's live-data model."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="CBAM Visualization",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(NoCacheMiddleware)
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
    app.mount("/", StaticFiles(directory=config.PUBLIC_DIR, html=True), name="static")

    return app


app = create_app()
