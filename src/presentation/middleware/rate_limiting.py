"""Rate limiting middleware — per-user (JWT sub), 3 windows, response headers."""

import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

import structlog
from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger()

# Window durations (seconds)
_WINDOW_MINUTE = 60.0
_WINDOW_HOUR = 3600.0
_BURST_WINDOW = 1.0

# Limit constants — module-level so tests can patch them at runtime.
# _MAX_REQUESTS is the canonical per-minute name (kept for test compatibility).
_MAX_REQUESTS = 60  # per-minute limit (tests patch this)
_MAX_PER_MINUTE = 60  # alias — dispatch reads _MAX_REQUESTS
_MAX_PER_HOUR = 1000
_MAX_BURST = 10

# Legacy module-level dict kept so existing tests that call _request_log.clear()
# don't raise AttributeError — no longer used by the middleware itself.
_request_log: dict[str, list[float]] = defaultdict(list)

# Reference to this module so dispatch can read patched module-level values.
_this_module = sys.modules[__name__]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, requests_per_minute: int = _MAX_REQUESTS) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._counters: dict[str, list[float]] = defaultdict(list)

    # ── Key extraction ────────────────────────────────────────────────────────

    def _extract_key(self, request: Request) -> str:
        """Return 'user:<sub>' for authenticated requests, 'ip:<addr>' otherwise."""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer ") :]
            try:
                claims = jwt.get_unverified_claims(token)
                sub = claims.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:  # noqa: S110
                pass  # Invalid/missing JWT — fall through to IP-based key
        ip = request.headers.get("X-Forwarded-For") or (
            request.client.host if request.client else "unknown"
        )
        return f"ip:{ip}"

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Read limits from module at call time so tests can patch them.
        max_per_minute: int = _this_module._MAX_REQUESTS
        max_per_hour: int = _this_module._MAX_PER_HOUR
        max_burst: int = _this_module._MAX_BURST

        key = self._extract_key(request)
        now = time.time()

        # Prune timestamps older than 1 hour
        self._counters[key] = [t for t in self._counters[key] if t > now - _WINDOW_HOUR]
        timestamps = self._counters[key]

        # Compute window counts
        burst_count = sum(1 for t in timestamps if t > now - _BURST_WINDOW)
        minute_count = sum(1 for t in timestamps if t > now - _WINDOW_MINUTE)
        hour_count = len(timestamps)

        # Check limits
        if burst_count >= max_burst or minute_count >= max_per_minute or hour_count >= max_per_hour:
            logger.warning(
                "rate_limit.exceeded",
                key=key,
                burst=burst_count,
                minute=minute_count,
                hour=hour_count,
            )
            retry_after = int(_WINDOW_MINUTE)
            if timestamps:
                oldest = min(timestamps)
                retry_after = max(1, int(oldest + _WINDOW_MINUTE - now))
            return JSONResponse(
                status_code=429,
                content={"error": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        # Record this request
        self._counters[key].append(now)
        minute_count_after = minute_count + 1

        response = await call_next(request)

        # Add rate limit response headers
        response.headers["X-RateLimit-Limit"] = str(max_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(max(0, max_per_minute - minute_count_after))
        response.headers["X-RateLimit-Reset"] = str(int(now + _WINDOW_MINUTE))

        return response
