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
from fastapi.responses import ORJSONResponse

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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


class AccountBannedError(AppError):
    """
    The account is suspended for credential sharing.

    403 rather than 402: this is not something more money fixes, and routing it to the
    purchase sheet would be both wrong and insulting. The client sends it to the appeal page
    instead — which is the entire reason this is a typed error and not a bare HTTPException.

    LIVES HERE, NOT IN services/billing/credits.py, AND THAT MOVE WAS THE BUG FIX.

    It was defined next to the credit ledger and therefore raised from exactly one place:
    spending a credit. But the path that actually locks somebody out is core/security.py,
    the auth dependency every authenticated request passes through — and `core` cannot import
    from `services.billing`, so that path raised a bare `HTTPException` carrying the same
    sentence as prose and none of the structure.

    The consequence was the reported one. On the blocked path the client received an untyped
    403, so it had no way to tell a suspension from any other failure: it rendered the
    generic data-error card, which says "this is usually temporary, wait a moment and try
    again" — false — offers a Try again button that can never succeed, and provides no link
    to the appeal the message tells the user to go and find. A suspended account was a dead
    end on screen even though the appeal endpoint was reachable the whole time.

    `details.appealable` is what the client keys the appeal route off, and
    frontend/src/lib/api/error-envelope.test.ts already pinned that contract before anything
    rendered it.
    """

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            message=(
                "This account is suspended because it was used from two places at once. "
                "You can request a review."
            ),
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_BANNED",
            details={"reason": reason, "appealable": True},
        )


# ─── Error response shape ─────────────────────────────────────────────────────


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
    headers: dict[str, str] | None = None,
) -> ORJSONResponse:
    return ORJSONResponse(
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


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app. Call in main.py."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> ORJSONResponse:
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
    ) -> ORJSONResponse:
        logger.warning("request_validation_error", errors=exc.errors(), path=request.url.path)
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Request validation failed.",
            {"fields": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request, exc: Exception
    ) -> ORJSONResponse:
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
