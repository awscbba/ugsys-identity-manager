"""Domain exception handler and unhandled exception handler.

Maps domain exceptions to HTTP status codes and wraps all error responses
in the standard envelope format. Internal details are logged but never
exposed to API callers.

Envelope format:
{
    "error": { "code": "...", "message": "..." },
    "meta": { "request_id": "..." }
}
"""

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from src.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    RepositoryError,
    ValidationError,
)
from src.presentation.middleware.correlation_id import correlation_id_var

logger = structlog.get_logger()

STATUS_MAP: dict[type[DomainError], int] = {
    ValidationError: 422,
    NotFoundError: 404,
    ConflictError: 409,
    AuthenticationError: 401,
    AuthorizationError: 403,
    AccountLockedError: 423,
    RepositoryError: 500,
    ExternalServiceError: 502,
}


def _build_error_envelope(
    code: str,
    message: str,
    request_id: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the standard error envelope."""
    envelope: dict[str, object] = {
        "error": {"code": code, "message": message},
        "meta": {"request_id": request_id},
    }
    if extra:
        error_dict = envelope["error"]
        if isinstance(error_dict, dict):
            error_dict.update(extra)
    return envelope


async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Handle domain exceptions with correct HTTP status and envelope format."""
    status = STATUS_MAP.get(type(exc), 500)
    request_id = correlation_id_var.get("")

    logger.error(
        "domain_error",
        error_code=exc.error_code,
        message=exc.message,
        status=status,
        path=request.url.path,
    )

    extra: dict[str, object] = {}

    # Special handling for AccountLockedError — include retry_after_seconds
    if isinstance(exc, AccountLockedError):
        retry_after = exc.additional_data.get("retry_after_seconds", 0)
        extra["retry_after_seconds"] = retry_after

    # Special handling for AuthenticationError subtypes
    if isinstance(exc, AuthenticationError):
        if exc.error_code == "EMAIL_NOT_VERIFIED":
            extra["email_not_verified"] = True
        elif exc.error_code == "PASSWORD_CHANGE_REQUIRED":
            extra["require_password_change"] = True

    content = _build_error_envelope(
        code=exc.error_code,
        message=exc.user_message,
        request_id=request_id,
        extra=extra,
    )

    return JSONResponse(status_code=status, content=content)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with a generic 500 response.

    Full details are logged but never exposed to the client.
    """
    request_id = correlation_id_var.get("")

    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        exc_info=True,
    )

    content = _build_error_envelope(
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        request_id=request_id,
    )

    return JSONResponse(status_code=500, content=content)
