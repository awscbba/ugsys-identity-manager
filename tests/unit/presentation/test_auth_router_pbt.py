"""Bug condition exploration tests — Cross-Service Session (Task 1).

**Validates: Requirements 1.1, 1.2, 1.5, 1.7, 1.9**

These tests MUST FAIL on unfixed code — failure confirms the bugs exist.
DO NOT fix the tests or the code when they fail.
They encode the expected behavior and will pass after the fix is applied.

Bug conditions documented:
- Login response has no Set-Cookie header → confirms root cause #1
  (missing Response param in login handler)
- Refresh returns 422 on cookie-only request → confirms root cause #2
  (refresh_token field required in body by Pydantic)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.testclient import TestClient

from src.application.commands.authenticate_user import TokenPair
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.interfaces.auth_service import IAuthService
from src.presentation.api.v1.auth import get_auth_service, router

# ── Helpers ───────────────────────────────────────────────────────────────────

# Minimal structurally-valid JWT (not cryptographically signed — only for decoding)
_FAKE_JWT = (
    "eyJhbGciOiJSUzI1NiJ9"
    ".eyJzdWIiOiJ1c2VyMSIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSIsInJvbGVzIjpbXSwiZXhwIjo5OTk5OTk5OTk5fQ"
    ".sig"
)


def _make_mock_auth_service() -> MagicMock:
    """Return a mock IAuthService with sensible defaults for login and refresh."""
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
    return svc


def _make_app(mock_svc: MagicMock) -> tuple[FastAPI, TestClient]:
    """Build a minimal FastAPI app with the auth router and the mock service wired in."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_auth_service] = lambda: mock_svc
    return app, TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════════
# BUG CONDITION TESTS — Property 1
# These MUST FAIL on unfixed code.
# ═══════════════════════════════════════════════════════════════════════════════


def test_login_sets_no_cookie_bug_condition() -> None:
    """Bug 1.1: POST /api/v1/auth/login MUST set a Set-Cookie header.

    BUG: the login handler has no `response: Response` parameter, so it never
    calls response.set_cookie(). The Set-Cookie header is absent on unfixed code.

    Counterexample: Set-Cookie header absent from login response.
    EXPECTED OUTCOME: FAILS on unfixed code (confirms root cause #1).
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Str0ng!Pass"},
    )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    assert "set-cookie" in resp.headers, (
        "Expected Set-Cookie header in login response but it was absent. "
        "BUG: login handler does not inject `response: Response` and never calls "
        "response.set_cookie(). Root cause #1 confirmed."
    )


def test_refresh_rejects_cookie_only_bug_condition() -> None:
    """Bug 1.2: POST /api/v1/auth/refresh with cookie but empty body MUST return 200.

    BUG: RefreshRequest has `refresh_token: str` (required field). A request with
    an empty JSON body `{}` fails Pydantic validation and returns 422 before the
    handler is even called.

    Counterexample: POST /refresh with cookie + empty body → 422 Unprocessable Entity.
    EXPECTED OUTCOME: FAILS on unfixed code (confirms root cause #2).
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={},  # empty body — token should come from cookie
        cookies={"ugsys_refresh_token": "test-refresh-token"},
    )

    assert resp.status_code == 200, (
        f"Expected 200 (cookie-only refresh) but got {resp.status_code}: {resp.text}. "
        "BUG: RefreshRequest.refresh_token is a required field — Pydantic rejects empty body "
        "with 422 before the handler can read the cookie. Root cause #2 confirmed."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION PBT — body-only refresh still passes token to service
# This MUST PASS on unfixed code (body-only refresh works today).
# It is embedded here as a regression guard within the exploration suite.
# **Validates: Requirements 3.2**
# ═══════════════════════════════════════════════════════════════════════════════


@given(
    token=st.text(
        min_size=10,
        max_size=200,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    )
)
@settings(max_examples=50)
def test_body_only_refresh_always_passes_token_to_service(token: str) -> None:
    """Preservation 3.2: For any non-empty body token with no cookie, service.refresh
    is called with that exact token value.

    This confirms the body-only path (non-browser clients) works on unfixed code
    and must continue to work after the fix.

    EXPECTED OUTCOME: PASSES on unfixed code (body-only refresh is not broken).
    """
    mock_svc = _make_mock_auth_service()
    _, client = _make_app(mock_svc)

    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token},
        # No cookie — pure body-only request (non-browser client path)
    )

    assert resp.status_code == 200, (
        f"Expected 200 for body-only refresh but got {resp.status_code}: {resp.text}"
    )
    mock_svc.refresh.assert_called_once_with(RefreshTokenCommand(refresh_token=token))
    mock_svc.refresh.reset_mock()
