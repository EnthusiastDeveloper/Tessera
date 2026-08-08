"""Consistent error envelope: HTTP status + machine-readable code + human message.

See architecture-plan §3 ("Error envelope").
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Raise from a route handler to produce the standard error envelope."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _envelope(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message, **extra})


def register_error_handlers(app: FastAPI) -> None:
    """Register handlers so `AppError` and Pydantic validation failures both produce the envelope."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(422, "validation_error", "Request validation failed.", details=jsonable_encoder(exc.errors()))
