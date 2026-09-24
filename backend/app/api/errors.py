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

#: HTTP status for every machine-readable error code a service raises (architecture-plan
#: §3). One table rather than one per route module: a code means the same thing, and
#: gets the same status, wherever it comes from.
ERROR_CODE_STATUS: dict[str, int] = {
    # Generic
    "not_found": 404,
    "invalid_field": 422,
    "scope_required": 422,
    "conflict": 409,
    # Task templates/instances (design doc §6.1, §6.5, §6.8, §3.2)
    "creation_conflict": 409,
    "cycle_detected": 409,
    "infeasible_duration": 422,
    "invalid_recurrence_anchor": 422,
    # Settings (§3.7)
    "invalid_timezone": 422,
    "invalid_day_map": 422,
    "settings_not_initialized": 500,
    # Auth (§3.6, §14.2)
    "already_configured": 410,
    "invalid_setup_token": 401,
    "password_too_short": 422,
    "invalid_credentials": 401,
    "too_many_attempts": 429,
    # Calendar sync (§3.5, §7)
    "app_base_url_not_configured": 400,
    "invalid_oauth_state": 400,
    "provider_not_configured": 400,
    "oauth_exchange_failed": 502,
    "token_refresh_failed": 502,
    "calendar_fetch_failed": 502,
}


class AppError(Exception):
    """Raise from a route handler to produce the standard error envelope."""

    def __init__(self, status_code: int, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    @classmethod
    def for_code(cls, code: str, message: str, *, details: dict[str, Any] | None = None) -> AppError:
        """An `AppError` whose HTTP status comes from `ERROR_CODE_STATUS`."""
        return cls(ERROR_CODE_STATUS[code], code, message, details=details)


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
