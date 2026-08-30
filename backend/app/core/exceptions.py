"""
Application Exceptions — core/exceptions.py

Centralized exception hierarchy and FastAPI exception handlers.

Design:
  - All application-level errors extend AppError.
  - AppError subclasses map to specific HTTP status codes.
  - The global exception handler in main.py catches AppError and returns
    a consistent JSON error response.
  - Third-party exceptions (e.g., DB errors) are caught and re-raised as AppError.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


# ─── Application exception hierarchy ─────────────────────────────────────────


class AppError(Exception):
    """
    Base application error.
    All custom exceptions must inherit from this.
    """

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: Any = None) -> None:
        detail = f" with id '{resource_id}'" if resource_id else ""
        super().__init__(
            message=f"{resource}{detail} not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            details={"resource": resource, "id": str(resource_id) if resource_id else None},
        )


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
        )


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
        )


class ConflictError(AppError):
    def __init__(self, message: str, resource: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="CONFLICT",
            details={"resource": resource} if resource else {},
        )


class ValidationError(AppError):
    def __init__(self, message: str, fields: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            details={"fields": fields} if fields else {},
        )


class InterviewError(AppError):
    """Raised when the interview engine encounters an unrecoverable error."""

    def __init__(self, message: str, session_id: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERVIEW_ENGINE_ERROR",
            details={"session_id": session_id} if session_id else {},
        )


class AIProviderUnavailableError(AppError):
    """Raised when all AI provider retries are exhausted."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            message=f"AI provider '{provider}' is unavailable. Please try again later.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AI_PROVIDER_UNAVAILABLE",
            details={"provider": provider},
        )


class StorageError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="STORAGE_ERROR",
        )


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # JSONResponse, not ORJSONResponse. FastAPI deprecated the orjson response class outright,
    # and it was still firing here after the app-level default was removed — five warnings in a
    # single test file. Nothing is lost: an error payload is a dict of strings and a status
    # code, with none of the datetime/UUID/numpy types orjson exists to serialise faster.
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
        headers=headers,
    )


def _cors_headers(request: Request) -> dict[str, str]:
    """
    CORS headers for an error response, echoing an allowed Origin.

    Needed because a handler registered for bare `Exception` is invoked by
    Starlette's ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware — so its
    response never passes through the CORS layer and carries no
    Access-Control-Allow-Origin. The browser then reports the 500 as "blocked by
    CORS policy" and hides the real error entirely, which makes every unhandled
    server error look like a CORS misconfiguration and is genuinely hard to debug.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}

    from app.core.config import settings  # noqa: PLC0415

    allowed = set(settings.CORS_ORIGINS)
    if origin not in allowed and not settings.is_development:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


# ─── Exception handlers ───────────────────────────────────────────────────────


def _safe_validation_errors(exc: RequestValidationError) -> list[dict]:
    """
    Pydantic's error list, reduced to what is safe to send back.

    THIS FIXES A 500 THAT WAS LIVE. `exc.errors()` was passed into `JSONResponse` verbatim,
    and for a Pydantic v2 `value_error` — which is what ANY `field_validator` raising
    `ValueError` produces — that dict carries `ctx: {"error": ValueError(...)}`. A raw
    exception object is not JSON-serialisable, so building the 422 threw, the throw fell
    through to the unhandled-exception handler, and the caller got a 500 for a request that
    was merely malformed.

    It was not theoretical: `api/v1/admin_offers.py` has five such validators — the offer
    kind, the value range, the percent bound, the item ids — and every one of them was
    answering 500. Nothing noticed, because a 500 on a bad admin request reads as a bug in
    the request.

    `input` AND `url` ARE DROPPED TOO, and that is deliberate rather than incidental.
    `input` is the caller's own bytes reflected back into an error body — the structured log
    line already redacts it, and an error response is a poor place to start echoing user
    data. `url` is a link to pydantic.dev, which is not useful to a candidate and names an
    internal dependency and its version.

    `loc` is kept, joined into a dotted path, because "which field" is the entire value of a
    validation error to whoever has to fix the request.
    """
    safe: list[dict] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        safe.append(
            {
                "field": location or "body",
                "type": str(error.get("type", "invalid")),
                # `msg` is authored by pydantic or by our own validator — never by the
                # caller — so it is safe to return and is the actionable half.
                "message": str(error.get("msg", "Invalid value.")),
            }
        )
    return safe


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app. Call in main.py."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            path=request.url.path,
        )
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("request_validation_error", errors=exc.errors(), path=request.url.path)
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "Request validation failed.",
            {"fields": _safe_validation_errors(exc)},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred. Our team has been notified.",
            headers=_cors_headers(request),
        )
