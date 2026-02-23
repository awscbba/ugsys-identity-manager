"""Correlation ID middleware — X-Request-ID propagation."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        correlation_id_var.set(request_id)
        with structlog.contextvars.bound_contextvars(correlation_id=request_id):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
