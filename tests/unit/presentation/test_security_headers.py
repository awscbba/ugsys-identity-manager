"""Bug condition exploration tests — Security Headers (Gap 1).

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
They encode the expected behavior and will pass after the fix is applied.
"""

from fastapi import FastAPI
from starlette.testclient import TestClient

from src.presentation.middleware.security_headers import SecurityHeadersMiddleware


def _make_app(path: str = "/ping") -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping() -> dict:  # type: ignore[type-arg]
        return {"ok": True}

    @app.get("/api/v1/users")
    async def users() -> dict:  # type: ignore[type-arg]
        return {"users": []}

    @app.get("/health")
    async def health() -> dict:  # type: ignore[type-arg]
        return {"status": "ok"}

    return app, TestClient(app)


# ── Bug 1.1: X-XSS-Protection must be "0" ────────────────────────────────────


def test_xss_protection_header_is_zero() -> None:
    """Requirement 2.1: X-XSS-Protection must be '0', not '1; mode=block'.

    BUG: currently returns '1; mode=block' which re-enables the legacy XSS
    filter known to introduce vulnerabilities.
    Counterexample: X-XSS-Protection: 1; mode=block
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert resp.headers.get("x-xss-protection") == "0", (
        f"Expected '0' but got '{resp.headers.get('x-xss-protection')}'"
    )


# ── Bug 1.2: HSTS must include preload ───────────────────────────────────────


def test_hsts_contains_preload() -> None:
    """Requirement 2.2: Strict-Transport-Security must include 'preload'.

    BUG: currently 'max-age=31536000; includeSubDomains' — missing 'preload'.
    Counterexample: Strict-Transport-Security: max-age=31536000; includeSubDomains
    """
    _, client = _make_app()
    resp = client.get("/ping")
    hsts = resp.headers.get("strict-transport-security", "")
    assert "preload" in hsts, f"Expected 'preload' in Strict-Transport-Security but got: '{hsts}'"


# ── Bug 1.4: Permissions-Policy must be present ──────────────────────────────


def test_permissions_policy_header_present() -> None:
    """Requirement 2.4: Permissions-Policy header must be present.

    BUG: currently missing entirely.
    Counterexample: header absent from response
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert "permissions-policy" in resp.headers, (
        "Expected 'Permissions-Policy' header but it was absent"
    )


# ── Bug 1.4: Cross-Origin-Opener-Policy must be present ──────────────────────


def test_cross_origin_opener_policy_present() -> None:
    """Requirement 2.4: Cross-Origin-Opener-Policy header must be present.

    BUG: currently missing entirely.
    Counterexample: header absent from response
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert "cross-origin-opener-policy" in resp.headers, (
        "Expected 'Cross-Origin-Opener-Policy' header but it was absent"
    )


# ── Bug 1.4: Cross-Origin-Resource-Policy must be present ────────────────────


def test_cross_origin_resource_policy_present() -> None:
    """Requirement 2.4: Cross-Origin-Resource-Policy header must be present.

    BUG: currently missing entirely.
    Counterexample: header absent from response
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert "cross-origin-resource-policy" in resp.headers, (
        "Expected 'Cross-Origin-Resource-Policy' header but it was absent"
    )


# ── Bug 1.5: Server header must NOT be present ───────────────────────────────


def test_server_header_not_exposed() -> None:
    """Requirement 2.6: Server header must be removed to prevent fingerprinting.

    BUG: the SecurityHeadersMiddleware does not actively remove the Server header.
    In production (uvicorn), the Server header is exposed as 'uvicorn'.
    The middleware must call response.headers.pop("server", None) to strip it.

    We verify the middleware has the removal logic by checking the dispatch method
    source — the fix requires an explicit pop() call.
    Counterexample: middleware dispatch() has no server header removal.
    """
    import inspect

    from src.presentation.middleware.security_headers import SecurityHeadersMiddleware

    source = inspect.getsource(SecurityHeadersMiddleware.dispatch)
    assert "server" in source.lower() and ("pop" in source or "del" in source), (
        "Expected SecurityHeadersMiddleware.dispatch() to contain server header removal "
        "(e.g. response.headers.pop('server', None)) but it was not found. "
        "BUG: Server header is not stripped by the middleware."
    )


# ── Bug 1.4: Cache-Control on /api/* paths ───────────────────────────────────


def test_cache_control_present_on_api_path() -> None:
    """Requirement 2.5: Cache-Control must be set on /api/* paths.

    BUG: currently missing on all paths.
    Counterexample: Cache-Control header absent on /api/v1/users
    """
    _, client = _make_app()
    resp = client.get("/api/v1/users")
    cache_control = resp.headers.get("cache-control", "")
    assert "no-store" in cache_control, (
        f"Expected 'no-store' in Cache-Control on /api/ path but got: '{cache_control}'"
    )
    assert "no-cache" in cache_control, (
        f"Expected 'no-cache' in Cache-Control on /api/ path but got: '{cache_control}'"
    )
    assert "must-revalidate" in cache_control, (
        f"Expected 'must-revalidate' in Cache-Control on /api/ path but got: '{cache_control}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION TESTS — Property 2: Baseline behavior that MUST NOT break
# **Validates: Requirements 3.10**
# These tests MUST PASS on unfixed code — they confirm the baseline to preserve.
# ═══════════════════════════════════════════════════════════════════════════════


def test_preservation_x_content_type_options_always_present() -> None:
    """Preservation 3.10: X-Content-Type-Options: nosniff must always be present.

    This header is already correct in unfixed code and must remain correct after the fix.
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert resp.headers.get("x-content-type-options") == "nosniff", (
        f"Expected 'nosniff' but got '{resp.headers.get('x-content-type-options')}'"
    )


def test_preservation_x_frame_options_always_present() -> None:
    """Preservation 3.10: X-Frame-Options: DENY must always be present.

    This header is already correct in unfixed code and must remain correct after the fix.
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert resp.headers.get("x-frame-options") == "DENY", (
        f"Expected 'DENY' but got '{resp.headers.get('x-frame-options')}'"
    )


def test_preservation_referrer_policy_always_present() -> None:
    """Preservation 3.10: Referrer-Policy: strict-origin-when-cross-origin must always be present.

    This header is already correct in unfixed code and must remain correct after the fix.
    """
    _, client = _make_app()
    resp = client.get("/ping")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
        f"Expected 'strict-origin-when-cross-origin' but got "
        f"'{resp.headers.get('referrer-policy')}'"
    )


def test_preservation_non_api_path_does_not_get_cache_control() -> None:
    """Preservation: Non-/api/ paths (e.g. /health) must NOT receive Cache-Control header.

    The Cache-Control header is only for /api/* paths per platform contract Section 9.2.
    Non-API paths like /health must not have it added.
    """
    _, client = _make_app()
    resp = client.get("/health")
    # On unfixed code, Cache-Control is absent everywhere (the bug is it's missing on /api/ too).
    # After the fix, it should only appear on /api/* paths — not on /health.
    cache_control = resp.headers.get("cache-control", "")
    assert "no-store" not in cache_control, (
        f"Cache-Control with 'no-store' must NOT be set on /health path, got: '{cache_control}'"
    )
