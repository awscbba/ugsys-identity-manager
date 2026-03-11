"""Preservation + cookie tests — Cross-Service Session (Tasks 2 & 3.3).

**Validates: Requirements 3.1, 3.2, 3.3, 3.6, 3.7, 3.8, 3.10**

Preservation tests MUST PASS on unfixed code — they confirm the baseline
behavior that must be preserved after the fix is applied.

Cookie tests verify the new httpOnly cookie behavior introduced by the fix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from src.application.commands.authenticate_user import TokenPair
from src.application.commands.logout import LogoutCommand
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.interfaces.auth_service import IAuthService
from src.domain.exceptions import AuthenticationError, DomainError
from src.presentation.api.v1.auth import get_auth_service, router
from src.presentation.middleware.exception_handler import domain_exception_handler

# ── Helpers ───────────────────────────────────────────────────────────────────

_FAKE_JWT = (
    "eyJhbGciOiJSUzI1NiJ9"
    ".eyJzdWIiOiJ1c2VyMSIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSIsInJvbGVzIjpbXSwiZXhwIjo5OTk5OTk5OTk5fQ"
    ".sig"
)


def _make_mock_auth_service() -> MagicMock:
    """Return a mock IAuthService with sensible defaults."""
    svc = MagicMock(spec=IAuthService)
    svc.authenticate = AsyncMock(
        return_value=TokenPair(
            access_token=_FAKE_JWT,
            refresh_token="test-refresh-token",
        )
    )
    svc.refresh = AsyncMock(
        return_value=TokenPair(
            access_token=_FAKE_JWT,
            refresh_token="new-refresh-token",
        )
    )
    svc.logout = AsyncMock(return_value=None)
    return svc


def _make_app(mock_svc: MagicMock) -> tuple[FastAPI, TestClient]:
    """Build a minimal FastAPI app with the auth router and exception handler wired in."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_auth_service] = lambda: mock_svc
    app.add_exception_handler(DomainError, domain_exception_handler)  # type: ignore[arg-type]
    return app, TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION TESTS — Property 3 & 4 + Requirements 3.3, 3.6
# These MUST PASS on unfixed code AND after the fix.
# ═══════════════════════════════════════════════════════════════════════════════


def test_login_returns_tokens_in_body() -> None:
    """Preservation 3.1 / Property 3: POST /login response body contains
    access_token and refresh_token as non-empty strings.

    Non-browser clients (mobile apps, CLI tools) depend on the JSON body.
    This must continue to work after the cookie fix is applied.
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    body = resp.json()
    data = body.get("data", body)
    assert "access_token" in data, f"access_token missing from response body: {data}"
    assert "refresh_token" in data, f"refresh_token missing from response body: {data}"
    assert isinstance(data["access_token"], str) and data["access_token"]
    assert isinstance(data["refresh_token"], str) and data["refresh_token"]


def test_refresh_body_only_returns_200() -> None:
    """Preservation 3.2 / Property 4: POST /refresh with valid token in JSON body
    and NO cookie returns 200 with a new access_token.
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "valid-body-refresh-token"},
    )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    body = resp.json()
    data = body.get("data", body)
    assert "access_token" in data
    assert isinstance(data["access_token"], str) and data["access_token"]
    mock_svc.refresh.assert_called_once_with(
        RefreshTokenCommand(refresh_token="valid-body-refresh-token")
    )


def test_login_failure_no_cookie() -> None:
    """Preservation 3.6: POST /login with wrong password returns 401 and
    does NOT set any Set-Cookie header.
    """
    mock_svc = _make_mock_auth_service()
    mock_svc.authenticate = AsyncMock(
        side_effect=AuthenticationError(
            message="Invalid credentials for test@example.com",
            user_message="Invalid email or password",
            error_code="AUTHENTICATION_FAILED",
        )
    )
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword!"},
    )

    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers, (
        "Expected NO Set-Cookie header on failed login, but one was present."
    )


def test_logout_body_token_still_works() -> None:
    """Preservation 3.3: POST /logout with body refresh_token and
    Authorization: Bearer header returns 200.
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "some-refresh-token"},
        headers={"Authorization": "Bearer some-access-token"},
    )

    assert resp.status_code == 200
    mock_svc.logout.assert_called_once_with(
        LogoutCommand(
            access_token="some-access-token",
            refresh_token="some-refresh-token",
        )
    )


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIE TESTS — Task 3.3 (new behavior after fix)
# ═══════════════════════════════════════════════════════════════════════════════


def test_login_sets_refresh_cookie() -> None:
    """Task 3.3: POST /login sets an httpOnly refresh token cookie with correct attributes."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code == 200
    assert "set-cookie" in resp.headers, "Expected Set-Cookie header in login response"

    cookie_header = resp.headers["set-cookie"]
    assert "ugsys_refresh_token" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()
    assert "Path=/api/v1/auth" in cookie_header
    assert "Max-Age=604800" in cookie_header  # 7 days


def test_refresh_cookie_takes_precedence_over_body() -> None:
    """Task 3.3: When both cookie and body token are present, cookie takes precedence."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "body-token"},
        cookies={"ugsys_refresh_token": "cookie-token"},
    )

    assert resp.status_code == 200
    # Cookie token takes precedence — service called with cookie token
    mock_svc.refresh.assert_called_once_with(RefreshTokenCommand(refresh_token="cookie-token"))


def test_refresh_cookie_only_returns_200() -> None:
    """Task 3.3: POST /refresh with cookie only (empty body) returns 200."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={},
        cookies={"ugsys_refresh_token": "cookie-only-token"},
    )

    assert resp.status_code == 200
    mock_svc.refresh.assert_called_once_with(RefreshTokenCommand(refresh_token="cookie-only-token"))


def test_refresh_no_token_returns_401() -> None:
    """Task 3.3: POST /refresh with no cookie and no body token returns 401."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={},
        # No cookie, no body token
    )

    assert resp.status_code == 401


def test_logout_clears_cookie() -> None:
    """Task 3.3: POST /logout clears the refresh token cookie (max_age=0)."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": "Bearer some-access-token"},
        cookies={"ugsys_refresh_token": "cookie-token"},
    )

    assert resp.status_code == 200
    assert "set-cookie" in resp.headers, "Expected Set-Cookie header to clear cookie on logout"
    cookie_header = resp.headers["set-cookie"]
    assert "ugsys_refresh_token" in cookie_header
    assert "Max-Age=0" in cookie_header


def test_refresh_sets_new_cookie_on_success() -> None:
    """Task 3.3 / Property 5: POST /refresh on success rotates the cookie (new Max-Age=604800)."""
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={},
        cookies={"ugsys_refresh_token": "old-token"},
    )

    assert resp.status_code == 200
    assert "set-cookie" in resp.headers
    cookie_header = resp.headers["set-cookie"]
    assert "Max-Age=604800" in cookie_header  # rotated with full TTL
    assert "new-refresh-token" in cookie_header
