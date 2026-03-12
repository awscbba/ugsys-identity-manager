"""CORS preflight regression tests — identity-manager.

Regression guard for the two bugs fixed in fix/cors-security-headers-options:
  1. RateLimitMiddleware was rate-limiting OPTIONS requests, dropping CORS headers.
  2. SecurityHeadersMiddleware was injecting Cross-Origin-Resource-Policy: same-origin
     onto OPTIONS responses, causing browsers to reject the preflight.

identity-manager has CORSMiddleware in create_app(). These tests replicate that
stack to ensure the full middleware chain handles preflights correctly.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from src.presentation.middleware.rate_limiting import RateLimitMiddleware, _request_log
from src.presentation.middleware.security_headers import SecurityHeadersMiddleware

_ALLOWED_ORIGIN = "https://auth.apps.cloud.org.bo"
_API_PATH = "/api/v1/auth/login"


def _make_app(requests_per_minute: int = 60) -> FastAPI:
    """Minimal app that mirrors the production middleware stack for identity-manager."""
    app = FastAPI()

    # CORSMiddleware — same config as create_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, requests_per_minute=requests_per_minute)

    @app.post(_API_PATH)
    async def login() -> dict:
        return {"token": "..."}

    @app.options(_API_PATH)
    async def login_options() -> dict:
        return {}

    return app


@pytest.fixture(autouse=True)
def clear_rate_limit_log() -> None:
    """Reset the rate limit counters between tests."""
    _request_log.clear()


# ── Preflight returns 200 with correct CORS headers ──────────────────────────


class TestOptionsPreflightReturnsCorrectCORSHeaders:
    """OPTIONS preflight must return 200 with CORS headers intact."""

    async def test_preflight_returns_200(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                _API_PATH,
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert response.status_code == 200

    async def test_preflight_returns_allow_origin(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                _API_PATH,
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert response.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN

    async def test_preflight_returns_allow_credentials(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                _API_PATH,
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert response.headers.get("access-control-allow-credentials") == "true"


# ── OPTIONS is not rate-limited ───────────────────────────────────────────────


class TestOptionsPreflightNotRateLimited:
    """OPTIONS requests must never be rate-limited (regression: RateLimitMiddleware bug)."""

    async def test_15_options_requests_never_return_429(self) -> None:
        # Use a very low limit to confirm OPTIONS bypasses it
        app = _make_app(requests_per_minute=2)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for i in range(15):
                response = await client.options(
                    _API_PATH,
                    headers={
                        "Origin": _ALLOWED_ORIGIN,
                        "Access-Control-Request-Method": "POST",
                    },
                )
                assert response.status_code != 429, (
                    f"OPTIONS request #{i + 1} was rate-limited (429) — "
                    "RateLimitMiddleware must pass OPTIONS through"
                )


# ── OPTIONS does not get Cross-Origin-Resource-Policy: same-origin ────────────


class TestOptionsPreflightNoCORPSameOrigin:
    """OPTIONS responses must not have CORP: same-origin.

    Regression: SecurityHeadersMiddleware was injecting this header on preflights.
    CORP: same-origin on a preflight response causes browsers to reject it.
    The fix: SecurityHeadersMiddleware short-circuits on OPTIONS.
    """

    async def test_corp_header_absent_on_options(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                _API_PATH,
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        corp = response.headers.get("cross-origin-resource-policy", "")
        assert corp != "same-origin", (
            "Cross-Origin-Resource-Policy: same-origin must not appear on OPTIONS preflight — "
            "it causes browsers to reject the preflight response"
        )

    async def test_no_security_headers_on_options(self) -> None:
        """SecurityHeadersMiddleware must not inject any headers on OPTIONS."""
        from src.presentation.middleware.security_headers import _SECURITY_HEADERS

        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.options(
                _API_PATH,
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        for header_key in _SECURITY_HEADERS:
            assert header_key.lower() not in response.headers, (
                f"Security header '{header_key}' must not be injected on OPTIONS preflight"
            )


# ── Non-OPTIONS requests still get security headers ───────────────────────────


class TestNonOptionsRequestsPreserveSecurityHeaders:
    """Regression guard: the OPTIONS fix must not break security headers on real requests."""

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def test_security_headers_present_on_non_options(self, method: str) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(
                method,
                _API_PATH,
                headers={"Origin": _ALLOWED_ORIGIN},
            )
        assert response.headers.get("cross-origin-resource-policy") == "cross-origin"
        assert response.headers.get("x-frame-options") == "DENY"
        assert response.headers.get("x-content-type-options") == "nosniff"
