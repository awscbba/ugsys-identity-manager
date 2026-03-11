"""Unit tests for presentation layer: exception_handler, response_envelope, roles."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from src.domain.entities.user import UserRole
from src.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    RepositoryError,
    ValidationError,
)
from src.presentation.api.v1.roles import _require_admin, _role_description
from src.presentation.middleware.exception_handler import (
    _build_error_envelope,
    domain_exception_handler,
    unhandled_exception_handler,
)
from src.presentation.response_envelope import list_response, success_response

# ─── Helpers ──────────────────────────────────────────────────────────────────


def make_mock_request(path: str = "/test") -> MagicMock:
    req = MagicMock(spec=Request)
    req.url.path = path
    return req


# ─── _build_error_envelope ────────────────────────────────────────────────────


def test_build_error_envelope_basic() -> None:
    result = _build_error_envelope("MY_CODE", "Something went wrong", "req-123")
    assert result["error"] == {"code": "MY_CODE", "message": "Something went wrong"}  # type: ignore[comparison-overlap]
    assert result["meta"] == {"request_id": "req-123"}  # type: ignore[comparison-overlap]


def test_build_error_envelope_with_extra() -> None:
    result = _build_error_envelope("CODE", "msg", "req-1", extra={"retry_after_seconds": 30})
    error = result["error"]
    assert isinstance(error, dict)
    assert error["retry_after_seconds"] == 30
    assert error["code"] == "CODE"


def test_build_error_envelope_no_extra() -> None:
    result = _build_error_envelope("CODE", "msg", "req-1", extra=None)
    error = result["error"]
    assert isinstance(error, dict)
    assert "retry_after_seconds" not in error


# ─── domain_exception_handler ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_domain_handler_validation_error() -> None:
    req = make_mock_request()
    exc = ValidationError(
        message="internal", user_message="Bad input", error_code="VALIDATION_ERROR"
    )
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 422
    import json

    body = json.loads(response.body)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Bad input"


@pytest.mark.asyncio
async def test_domain_handler_not_found() -> None:
    req = make_mock_request()
    exc = NotFoundError(message="internal", user_message="Not found")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_domain_handler_conflict() -> None:
    req = make_mock_request()
    exc = ConflictError(message="internal", user_message="Conflict")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_domain_handler_authentication_error() -> None:
    req = make_mock_request()
    exc = AuthenticationError(message="internal", user_message="Unauthorized")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_domain_handler_authorization_error() -> None:
    req = make_mock_request()
    exc = AuthorizationError(message="internal", user_message="Forbidden")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_domain_handler_account_locked_with_retry_after() -> None:
    req = make_mock_request()
    exc = AccountLockedError(
        message="locked",
        user_message="Account locked",
        error_code="ACCOUNT_LOCKED",
        additional_data={"retry_after_seconds": 30},
    )
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 423
    import json

    body = json.loads(response.body)
    assert body["error"]["retry_after_seconds"] == 30


@pytest.mark.asyncio
async def test_domain_handler_account_locked_no_retry_after() -> None:
    req = make_mock_request()
    exc = AccountLockedError(
        message="locked",
        user_message="Account locked",
        error_code="ACCOUNT_LOCKED",
    )
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 423
    import json

    body = json.loads(response.body)
    assert body["error"]["retry_after_seconds"] == 0


@pytest.mark.asyncio
async def test_domain_handler_email_not_verified() -> None:
    req = make_mock_request()
    exc = AuthenticationError(
        message="not verified",
        user_message="Verify email",
        error_code="EMAIL_NOT_VERIFIED",
    )
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 401
    import json

    body = json.loads(response.body)
    assert body["error"]["email_not_verified"] is True


@pytest.mark.asyncio
async def test_domain_handler_password_change_required() -> None:
    req = make_mock_request()
    exc = AuthenticationError(
        message="change pw",
        user_message="Change password",
        error_code="PASSWORD_CHANGE_REQUIRED",
    )
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 401
    import json

    body = json.loads(response.body)
    assert body["error"]["require_password_change"] is True


@pytest.mark.asyncio
async def test_domain_handler_repository_error() -> None:
    req = make_mock_request()
    exc = RepositoryError(message="db error", user_message="Unexpected error")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_domain_handler_external_service_error() -> None:
    req = make_mock_request()
    exc = ExternalServiceError(message="downstream", user_message="Service unavailable")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_domain_handler_unknown_domain_error_defaults_500() -> None:
    """An unmapped DomainError subclass should default to 500."""
    from src.domain.exceptions import DomainError

    req = make_mock_request()
    exc = DomainError(message="unknown", user_message="Error")
    response = await domain_exception_handler(req, exc)
    assert response.status_code == 500


# ─── unhandled_exception_handler ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_500() -> None:
    req = make_mock_request()
    exc = RuntimeError("something exploded")
    response = await unhandled_exception_handler(req, exc)
    assert response.status_code == 500
    import json

    body = json.loads(response.body)
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "An unexpected error occurred"


@pytest.mark.asyncio
async def test_unhandled_exception_handler_does_not_expose_details() -> None:
    req = make_mock_request()
    exc = ValueError("SELECT * FROM users WHERE id=1")
    response = await unhandled_exception_handler(req, exc)
    import json

    body = json.loads(response.body)
    assert "SELECT" not in body["error"]["message"]


# ─── success_response ─────────────────────────────────────────────────────────


def test_success_response_structure() -> None:
    result = success_response({"id": "123", "name": "Alice"}, "req-abc")
    assert result["data"] == {"id": "123", "name": "Alice"}
    assert result["meta"] == {"request_id": "req-abc"}  # type: ignore[comparison-overlap]


def test_success_response_with_none_data() -> None:
    result = success_response(None, "req-xyz")
    assert result["data"] is None
    assert result["meta"]["request_id"] == "req-xyz"  # type: ignore[index]


# ─── list_response ────────────────────────────────────────────────────────────


def test_list_response_structure() -> None:
    result = list_response([1, 2, 3], total=10, page=1, page_size=3, request_id="req-1")
    assert result["data"] == [1, 2, 3]
    meta = result["meta"]
    assert isinstance(meta, dict)
    assert meta["total"] == 10
    assert meta["page"] == 1
    assert meta["page_size"] == 3
    assert meta["total_pages"] == 4  # ceil(10/3)
    assert meta["request_id"] == "req-1"


def test_list_response_exact_pages() -> None:
    result = list_response([], total=9, page=1, page_size=3, request_id="r")
    meta = result["meta"]
    assert isinstance(meta, dict)
    assert meta["total_pages"] == 3


def test_list_response_page_size_zero() -> None:
    result = list_response([], total=10, page=1, page_size=0, request_id="r")
    meta = result["meta"]
    assert isinstance(meta, dict)
    assert meta["total_pages"] == 0


def test_list_response_single_page() -> None:
    result = list_response(["a"], total=1, page=1, page_size=10, request_id="r")
    meta = result["meta"]
    assert isinstance(meta, dict)
    assert meta["total_pages"] == 1


# ─── _require_admin ───────────────────────────────────────────────────────────


def make_credentials(token: str = "test-token") -> HTTPAuthorizationCredentials:  # noqa: S107  # gitguardian:ignore
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_require_admin_raises_401_on_invalid_token() -> None:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(side_effect=ValueError("bad token"))
    creds = make_credentials()
    with pytest.raises(HTTPException) as exc_info:
        await _require_admin(creds, token_svc)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_admin_raises_403_when_no_admin_role() -> None:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"roles": ["member"]})
    creds = make_credentials()
    with pytest.raises(HTTPException) as exc_info:
        await _require_admin(creds, token_svc)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_passes_with_admin_role() -> None:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"roles": ["admin"]})
    creds = make_credentials()
    # Should not raise
    await _require_admin(creds, token_svc)


@pytest.mark.asyncio
async def test_require_admin_passes_with_super_admin_role() -> None:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"roles": ["super_admin"]})
    creds = make_credentials()
    await _require_admin(creds, token_svc)


@pytest.mark.asyncio
async def test_require_admin_handles_non_list_roles() -> None:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"roles": None})
    creds = make_credentials()
    with pytest.raises(HTTPException) as exc_info:
        await _require_admin(creds, token_svc)
    assert exc_info.value.status_code == 403


# ─── _role_description ────────────────────────────────────────────────────────


def test_role_description_super_admin() -> None:
    desc = _role_description(UserRole.SUPER_ADMIN)
    assert "Full platform access" in desc


def test_role_description_admin() -> None:
    desc = _role_description(UserRole.ADMIN)
    assert "Administrative access" in desc


def test_role_description_member() -> None:
    desc = _role_description(UserRole.MEMBER)
    assert "Standard member" in desc


def test_role_description_unknown_returns_empty() -> None:
    # Use a role not in the descriptions dict (e.g. MODERATOR)
    desc = _role_description(UserRole.MODERATOR)
    assert desc == ""
