"""Consistent error envelope: HTTP status + machine-readable code + human message.

See architecture-plan §3 ("Error envelope").
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError


class AppError(Exception):
    """Raise from a route handler to produce the standard error envelope."""

    def __init__(self, status_code: int, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _envelope(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message, **extra})


def register_error_handlers(app: FastAPI) -> None:
    """Register handlers so `AppError` and Pydantic validation failures both produce the envelope."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        extra = {"details": jsonable_encoder(exc.details)} if exc.details is not None else {}
        return _envelope(exc.status_code, exc.code, exc.message, **extra)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(422, "validation_error", "Request validation failed.", details=jsonable_encoder(exc.errors()))

    @app.exception_handler(StaleDataError)
    async def _handle_stale_data_error(request: Request, exc: StaleDataError) -> JSONResponse:
        """architecture-plan §5.1's `version_id_col` backstop: a genuinely concurrent
        write (e.g. a background job) can still race between a service method's read
        and its flush, outside the `expected`-map window that check only covers. Map it
        to the same `conflict` envelope rather than letting it surface as a bare 500.
        """
        return _envelope(409, "conflict", "This task was modified concurrently. Reload and try again.")
