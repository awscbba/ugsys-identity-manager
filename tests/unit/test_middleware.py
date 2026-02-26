"""Unit tests for presentation middleware."""

from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from src.presentation.middleware.correlation_id import CorrelationIdMiddleware
from src.presentation.middleware.rate_limiting import RateLimitMiddleware
from src.presentation.middleware.request_logging import RequestLoggingMiddleware
from src.presentation.middleware.security_headers import SecurityHeadersMiddleware


def _app_with(*middleware_classes) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    for cls in middleware_classes:
        app.add_middleware(cls)

    @app.get("/ping")
    async def ping() -> dict:  # type: ignore[type-arg]
        return {"ok": True}

    return app


# ── CorrelationIdMiddleware ───────────────────────────────────────────────


def test_correlation_id_generated_when_missing() -> None:
    client = TestClient(_app_with(CorrelationIdMiddleware))
    resp = client.get("/ping")
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) == 36  # UUID format


def test_correlation_id_propagated_from_request() -> None:
    client = TestClient(_app_with(CorrelationIdMiddleware))
    resp = client.get("/ping", headers={"X-Request-ID": "my-trace-id"})
    assert resp.headers["x-request-id"] == "my-trace-id"


# ── SecurityHeadersMiddleware ─────────────────────────────────────────────


def test_security_headers_present() -> None:
    client = TestClient(_app_with(SecurityHeadersMiddleware))
    resp = client.get("/ping")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    # Hardened: XSS protection disabled — CSP is the correct defense (per security.md)
    assert resp.headers["x-xss-protection"] == "0"
    assert "max-age=31536000" in resp.headers["strict-transport-security"]
    assert "preload" in resp.headers["strict-transport-security"]
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


# ── RequestLoggingMiddleware ──────────────────────────────────────────────


def test_request_logging_calls_logger() -> None:
    with patch("src.presentation.middleware.request_logging.logger") as mock_log:
        client = TestClient(_app_with(RequestLoggingMiddleware))
        client.get("/ping")
    mock_log.info.assert_called_once()
    call_kwargs = mock_log.info.call_args
    assert call_kwargs[0][0] == "request"


# ── RateLimitMiddleware ───────────────────────────────────────────────────


def test_rate_limit_allows_normal_traffic() -> None:
    client = TestClient(_app_with(RateLimitMiddleware))
    for _ in range(5):
        resp = client.get("/ping")
        assert resp.status_code == 200


def test_rate_limit_blocks_after_threshold() -> None:
    """Rate limiter must return 429 after burst limit is exceeded."""
    # Each TestClient gets a fresh middleware instance with its own counters
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/ping")
    async def ping() -> dict:  # type: ignore[type-arg]
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    # Send 15 rapid requests from the same IP — burst limit is 10/sec
    responses = [client.get("/ping") for _ in range(15)]
    status_codes = [r.status_code for r in responses]
    assert 429 in status_codes
