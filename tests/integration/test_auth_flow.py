"""Preservation integration tests — auth flow baseline and rate limiting.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

These tests MUST PASS on unfixed code — they confirm the baseline behavior
that must not break after any fix is applied.
"""

from __future__ import annotations

import httpx

from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

_STRONG_PASSWORD = "Str0ng!Pass#1"
_USERS_TABLE = "ugsys-identity-manager-users-test"


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register(client: httpx.AsyncClient, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _STRONG_PASSWORD, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text


async def _get_verification_token(email: str) -> str:
    repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
    user = await repo.find_by_email(email)
    assert user is not None
    assert user.email_verification_token is not None
    return user.email_verification_token


async def _verify_email(client: httpx.AsyncClient, token: str) -> None:
    resp = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text


async def _register_verify_login(client: httpx.AsyncClient, email: str) -> dict:
    await _register(client, email)
    token = await _get_verification_token(email)
    await _verify_email(client, token)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _STRONG_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Preservation 3.6: GET /health returns 200 without auth ───────────────────


async def test_preservation_health_returns_200_without_auth(
    app_client: httpx.AsyncClient,
) -> None:
    """Preservation 3.6: GET /health must return 200 without any authentication.

    This is a baseline behavior that must not break after any fix.
    """
    resp = await app_client.get("/health")
    assert resp.status_code == 200, f"Expected 200 from /health but got {resp.status_code}"


# ── Preservation 3.7: Requests exceeding 60/min return 429 ──────────────────


async def test_preservation_rate_limit_60_per_min_returns_429(
    app_client: httpx.AsyncClient,
) -> None:
    """Preservation 3.7: Requests exceeding 60/min must return 429.

    The rate limiter enforces 60 req/min AND a 10 req/s burst limit.
    We patch _MAX_BURST to a high value so only the per-minute window is tested.
    """
    import src.presentation.middleware.rate_limiting as rl_module

    original_burst = rl_module._MAX_BURST
    rl_module._MAX_BURST = 10_000  # disable burst limit for this test
    try:
        # Send 60 requests — all should succeed (minute window not yet exhausted)
        for i in range(60):
            resp = await app_client.get("/health")
            assert resp.status_code != 429, (
                f"Request {i + 1} returned 429 unexpectedly — rate limit triggered too early"
            )

        # 61st request must be rate-limited by the per-minute window
        resp = await app_client.get("/health")
        assert resp.status_code == 429, (
            f"Expected 429 on 61st request but got {resp.status_code}. "
            "Rate limiting must still enforce 60 req/min."
        )
    finally:
        rl_module._MAX_BURST = original_burst
