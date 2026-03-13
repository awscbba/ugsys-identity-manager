"""Bug condition exploration tests — Rate Limiting (Gap 3).

**Validates: Requirements 1.10, 1.11, 1.12, 1.13**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.presentation.middleware.rate_limiting import RateLimitMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/ping")
    async def ping() -> dict:  # type: ignore[type-arg]
        return {"ok": True}

    return app


def _make_jwt_token(sub: str, secret: str = "test-secret") -> str:  # noqa: S107
    """Create a minimal HS256 JWT with a given sub claim for test purposes."""
    payload = {"sub": sub, "exp": int(time.time()) + 3600}
    result: str = jwt.encode(payload, secret, algorithm="HS256")
    return result


# ── Bug 1.10: Per-user keying (JWT sub), not IP-only ─────────────────────────


def test_same_jwt_sub_different_ips_share_counter() -> None:
    """Requirement 2.11: Rate limit must be keyed by JWT sub, not IP.

    BUG: currently keyed by IP (X-Forwarded-For / client.host), so the same
    user from two different IPs gets two independent counters.
    Counterexample: user with sub='user-123' from IP-A and IP-B each get
    their own 60-req window instead of sharing one.
    """
    import src.presentation.middleware.rate_limiting as rl_module

    rl_module._request_log.clear()  # type: ignore[attr-defined]
    # Lower threshold so we can hit it quickly
    original_max = rl_module._MAX_REQUESTS  # type: ignore[attr-defined]
    rl_module._MAX_REQUESTS = 3  # type: ignore[attr-defined]

    app = _make_app()
    token = _make_jwt_token(sub="user-abc-123")
    auth_header = f"Bearer {token}"

    try:
        client = TestClient(app, raise_server_exceptions=False)

        # Send 3 requests from IP-A — should exhaust the per-user limit
        for _ in range(3):
            client.get(
                "/ping",
                headers={"Authorization": auth_header, "X-Forwarded-For": "10.0.0.1"},
            )

        # 4th request from a DIFFERENT IP but SAME JWT sub — must be 429
        resp = client.get(
            "/ping",
            headers={"Authorization": auth_header, "X-Forwarded-For": "10.0.0.2"},
        )
        assert resp.status_code == 429, (
            f"Expected 429 (same user, different IP) but got {resp.status_code}. "
            "BUG: rate limiter is IP-keyed, not user-keyed."
        )
    finally:
        rl_module._MAX_REQUESTS = original_max  # type: ignore[attr-defined]
        rl_module._request_log.clear()  # type: ignore[attr-defined]


# ── Bug 1.11: Burst window (10 req/sec) not enforced ─────────────────────────


def test_burst_limit_enforced_within_one_second() -> None:
    """Requirement 2.13: 10 req/second burst limit must be enforced.

    BUG: currently only enforces 60 req/min window; no burst window exists.
    Counterexample: 11 requests in <1 second all return 200.
    """
    import src.presentation.middleware.rate_limiting as rl_module

    rl_module._request_log.clear()  # type: ignore[attr-defined]

    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Patch time.time() to return the same timestamp for all 11 requests
    # so they all fall within the same 1-second burst window
    fixed_time = time.time()
    with patch("src.presentation.middleware.rate_limiting.time") as mock_time:
        mock_time.time.return_value = fixed_time

        responses = [client.get("/ping") for _ in range(11)]

    status_codes = [r.status_code for r in responses]
    assert 429 in status_codes, (
        f"Expected at least one 429 for 11 requests in 1 second, "
        f"but all returned: {status_codes}. BUG: burst window not enforced."
    )

    rl_module._request_log.clear()  # type: ignore[attr-defined]


# ── Bug 1.12: X-RateLimit-Limit header missing on 200 ────────────────────────


def test_x_ratelimit_limit_header_present_on_200() -> None:
    """Requirement 2.14: X-RateLimit-Limit must be present on every response.

    BUG: currently no X-RateLimit-* headers are set on any response.
    Counterexample: 200 response missing X-RateLimit-Limit header.
    """
    import src.presentation.middleware.rate_limiting as rl_module

    rl_module._request_log.clear()  # type: ignore[attr-defined]

    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/ping")

    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers, (
        "Expected 'X-RateLimit-Limit' header on 200 response but it was absent. "
        "BUG: rate limit response headers not implemented."
    )

    rl_module._request_log.clear()  # type: ignore[attr-defined]


# ── Bug 1.12: Retry-After header missing on 429 ──────────────────────────────


def test_x_ratelimit_remaining_header_present_on_200() -> None:
    """Requirement 2.14: X-RateLimit-Remaining must be present on every response.

    BUG: currently no X-RateLimit-* headers are set on any response.
    Counterexample: 200 response missing X-RateLimit-Remaining header.
    """
    import src.presentation.middleware.rate_limiting as rl_module

    rl_module._request_log.clear()  # type: ignore[attr-defined]

    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/ping")

    assert resp.status_code == 200
    assert "x-ratelimit-remaining" in resp.headers, (
        "Expected 'X-RateLimit-Remaining' header on 200 response but it was absent. "
        "BUG: rate limit response headers not implemented."
    )

    rl_module._request_log.clear()  # type: ignore[attr-defined]
