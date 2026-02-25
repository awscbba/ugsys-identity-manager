"""Domain exception hierarchy for ugsys-identity-manager.

All application and domain layer code MUST use these exceptions.
Never raise raw Exception, ValueError, or HTTPException from application or domain layers.

Each exception carries two messages:
- message: internal detail for logs only
- user_message: safe message returned to the API client
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainError(Exception):
    """Base for all domain errors. Never expose internal details to callers."""

    message: str
    user_message: str = "An error occurred"
    error_code: str = "INTERNAL_ERROR"
    additional_data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


# ── Validation ────────────────────────────────────────────────────────────────


@dataclass
class ValidationError(DomainError):
    """Input failed business rule validation. HTTP 422."""

    error_code: str = "VALIDATION_ERROR"


@dataclass
class NotFoundError(DomainError):
    """Requested resource does not exist. HTTP 404."""

    error_code: str = "NOT_FOUND"


@dataclass
class ConflictError(DomainError):
    """Resource already exists or state conflict. HTTP 409."""

    error_code: str = "CONFLICT"


# ── Auth ──────────────────────────────────────────────────────────────────────


@dataclass
class AuthenticationError(DomainError):
    """Identity could not be verified. HTTP 401."""

    error_code: str = "AUTHENTICATION_FAILED"


@dataclass
class AuthorizationError(DomainError):
    """Authenticated identity lacks required permission. HTTP 403."""

    error_code: str = "FORBIDDEN"


@dataclass
class AccountLockedError(DomainError):
    """Account is locked. HTTP 423."""

    error_code: str = "ACCOUNT_LOCKED"


# ── Infrastructure ────────────────────────────────────────────────────────────


@dataclass
class RepositoryError(DomainError):
    """Data access failure. HTTP 500. Never expose DB details."""

    error_code: str = "REPOSITORY_ERROR"


@dataclass
class ExternalServiceError(DomainError):
    """Downstream service call failed. HTTP 502."""

    error_code: str = "EXTERNAL_SERVICE_ERROR"
