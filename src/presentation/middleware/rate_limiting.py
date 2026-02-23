"""Rate limiting middleware — per-user, 60 req/min default."""

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger()

# Simple in-memory store: {key: [timestamps]}
_request_log: dict[str, list[float]] = defaultdict(list)
_WINDOW = 60.0  # seconds
_MAX_REQUESTS = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = request.headers.get("X-Forwarded-For") or (
            request.client.host if request.client else "unknown"
        )
        now = time.time()
        window_start = now - _WINDOW
        hits = _request_log[key]
        # Prune old entries
        _request_log[key] = [t for t in hits if t > window_start]
        if len(_request_log[key]) >= _MAX_REQUESTS:
            logger.warning("rate_limit.exceeded", client=key)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(int(_WINDOW))},
            )
        _request_log[key].append(now)
        return await call_next(request)
