"""X-Ray tracing middleware — opens a segment per request, annotates with correlation ID."""

from collections.abc import Awaitable, Callable

import structlog
from aws_xray_sdk.core import xray_recorder  # type: ignore[import-untyped]
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.presentation.middleware.correlation_id import correlation_id_var

logger = structlog.get_logger()


class TracingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, service_name: str = "ugsys-identity-manager") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._service_name = service_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Lambda runtime creates the root segment; we create a subsegment here
        segment_name = f"{request.method} {request.url.path}"
        with xray_recorder.in_subsegment(segment_name) as subsegment:
            if subsegment:
                subsegment.put_annotation("http_method", request.method)
                subsegment.put_annotation("http_path", request.url.path)
                correlation_id = correlation_id_var.get("")
                if correlation_id:
                    subsegment.put_annotation("correlation_id", correlation_id)

            response = await call_next(request)

            if subsegment:
                subsegment.put_annotation("http_status", response.status_code)
                if response.status_code >= 500:
                    subsegment.put_error_flag()
                elif response.status_code >= 400:
                    subsegment.put_fault_flag()

        return response
