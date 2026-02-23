"""Unit tests for TracingMiddleware."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.responses import Response
from starlette.testclient import TestClient

from src.presentation.middleware.tracing import TracingMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TracingMiddleware, service_name="test-service")

    @app.get("/test")
    async def test_route() -> dict:  # type: ignore[type-arg]
        return {"ok": True}

    @app.get("/error")
    async def error_route() -> Response:
        return Response(status_code=500)

    return app


@pytest.fixture
def mock_subsegment() -> MagicMock:
    sub = MagicMock()
    sub.__enter__ = MagicMock(return_value=sub)
    sub.__exit__ = MagicMock(return_value=False)
    return sub


def test_tracing_annotates_successful_request(mock_subsegment: MagicMock) -> None:
    with patch(
        "src.presentation.middleware.tracing.xray_recorder.in_subsegment",
        return_value=mock_subsegment,
    ):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        resp = client.get("/test")

    assert resp.status_code == 200
    mock_subsegment.put_annotation.assert_any_call("http_method", "GET")
    mock_subsegment.put_annotation.assert_any_call("http_path", "/test")
    mock_subsegment.put_annotation.assert_any_call("http_status", 200)


def test_tracing_marks_server_error(mock_subsegment: MagicMock) -> None:
    with patch(
        "src.presentation.middleware.tracing.xray_recorder.in_subsegment",
        return_value=mock_subsegment,
    ):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        client.get("/error")

    mock_subsegment.put_error_flag.assert_called_once()


def test_tracing_skipped_when_subsegment_is_none() -> None:
    """context_missing=LOG_ERROR means subsegment can be None outside Lambda — must not crash."""
    none_ctx = MagicMock()
    none_ctx.__enter__ = MagicMock(return_value=None)
    none_ctx.__exit__ = MagicMock(return_value=False)

    with patch(
        "src.presentation.middleware.tracing.xray_recorder.in_subsegment",
        return_value=none_ctx,
    ):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        resp = client.get("/test")

    assert resp.status_code == 200
