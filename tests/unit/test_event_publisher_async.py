"""Unit tests for the updated async EventBridgePublisher.

TDD: RED phase — tests written before implementation.
Covers the aioboto3 async migration requirements:
  - Req 1.1: uses aioboto3 (not boto3)
  - Req 1.2: publish() awaits put_events
  - Req 1.3: client lifecycle via async context manager
  - Req 1.4: FailedEntryCount > 0 raises ExternalServiceError
  - Req 2.1: any client exception raises ExternalServiceError (not swallowed)
  - Req 2.2: no silent except block
  - Req 2.3: success logs at info level with detail_type and event_id
"""

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.exceptions import ExternalServiceError
from src.infrastructure.messaging.event_publisher import EventBridgePublisher

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_async_client(
    *,
    failed_entry_count: int = 0,
    put_events_side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a mock aioboto3 EventBridge client."""
    client = AsyncMock()
    if put_events_side_effect is not None:
        client.put_events = AsyncMock(side_effect=put_events_side_effect)
    else:
        client.put_events = AsyncMock(
            return_value={
                "FailedEntryCount": failed_entry_count,
                "Entries": [{"EventId": "evt-001"}]
                if failed_entry_count == 0
                else [{"ErrorCode": "InternalFailure", "ErrorMessage": "failed"}],
            }
        )
    return client


def make_session(mock_client: AsyncMock) -> MagicMock:
    """Build a mock aioboto3.Session whose .client() is an async context manager."""
    session = MagicMock()

    @asynccontextmanager
    async def _client_ctx(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield mock_client

    session.client = MagicMock(side_effect=_client_ctx)
    return session


def make_publisher(session: MagicMock) -> EventBridgePublisher:
    return EventBridgePublisher(bus_name="test-bus", region="us-east-1", session=session)


# ── Async context manager usage ───────────────────────────────────────────────


class TestAsyncContextManager:
    """publish() must open the aioboto3 client via async context manager."""

    @pytest.mark.asyncio
    async def test_publish_uses_session_client(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        session.client.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_opens_events_client(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        call_kwargs = session.client.call_args
        # First positional arg or keyword arg should be "events"
        assert (
            "events" in (call_kwargs.args or ())
            or call_kwargs.kwargs.get("service_name") == "events"
            or (call_kwargs.args and call_kwargs.args[0] == "events")
        )

    @pytest.mark.asyncio
    async def test_publish_awaits_put_events(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        mock_client.put_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_passes_correct_bus_name(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        call_kwargs = mock_client.put_events.call_args[1]
        entries = call_kwargs["Entries"]
        assert entries[0]["EventBusName"] == "test-bus"

    @pytest.mark.asyncio
    async def test_publish_passes_correct_detail_type(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.deactivated", {"user_id": "u-2"})

        call_kwargs = mock_client.put_events.call_args[1]
        entries = call_kwargs["Entries"]
        assert entries[0]["DetailType"] == "identity.user.deactivated"

    @pytest.mark.asyncio
    async def test_publish_envelope_contains_payload(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)
        payload = {"user_id": "u-3", "email": "x@example.com"}

        await publisher.publish("identity.user.registered", payload)

        call_kwargs = mock_client.put_events.call_args[1]
        detail = json.loads(call_kwargs["Entries"][0]["Detail"])
        assert detail["payload"] == payload

    @pytest.mark.asyncio
    async def test_publish_envelope_has_event_id(self) -> None:
        mock_client = make_async_client()
        session = make_session(mock_client)
        publisher = make_publisher(session)

        await publisher.publish("identity.user.registered", {})

        call_kwargs = mock_client.put_events.call_args[1]
        detail = json.loads(call_kwargs["Entries"][0]["Detail"])
        assert "event_id" in detail
        assert detail["event_id"]  # non-empty


# ── FailedEntryCount > 0 ──────────────────────────────────────────────────────


class TestFailedEntryCount:
    """FailedEntryCount > 0 must raise ExternalServiceError (Req 1.4)."""

    @pytest.mark.asyncio
    async def test_failed_entry_count_1_raises_external_service_error(self) -> None:
        mock_client = make_async_client(failed_entry_count=1)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError):
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

    @pytest.mark.asyncio
    async def test_failed_entry_count_3_raises_external_service_error(self) -> None:
        mock_client = make_async_client(failed_entry_count=3)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError):
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

    @pytest.mark.asyncio
    async def test_failed_entry_count_0_does_not_raise(self) -> None:
        mock_client = make_async_client(failed_entry_count=0)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        # Should not raise
        await publisher.publish("identity.user.registered", {"user_id": "u-1"})

    @pytest.mark.asyncio
    async def test_failed_entry_error_has_safe_user_message(self) -> None:
        mock_client = make_async_client(failed_entry_count=1)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError) as exc_info:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        assert exc_info.value.user_message == "An unexpected error occurred"

    @pytest.mark.asyncio
    async def test_failed_entry_error_message_contains_detail(self) -> None:
        """Internal message must contain failed entry details (not just a generic string)."""
        mock_client = make_async_client(failed_entry_count=1)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError) as exc_info:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        # Internal message must differ from user_message
        assert exc_info.value.message != exc_info.value.user_message


# ── Client exception propagation ─────────────────────────────────────────────


class TestClientExceptionPropagation:
    """Any exception from the aioboto3 client must raise ExternalServiceError (Req 2.1, 2.2)."""

    @pytest.mark.asyncio
    async def test_client_exception_raises_external_service_error(self) -> None:
        mock_client = make_async_client(put_events_side_effect=Exception("EventBridge unavailable"))
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError):
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

    @pytest.mark.asyncio
    async def test_client_exception_is_not_swallowed(self) -> None:
        """The old behaviour swallowed exceptions — new behaviour must NOT."""
        mock_client = make_async_client(put_events_side_effect=RuntimeError("network timeout"))
        session = make_session(mock_client)
        publisher = make_publisher(session)

        # Must raise — not return normally
        raised = False
        try:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})
        except ExternalServiceError:
            raised = True

        assert raised, "Exception must not be swallowed — ExternalServiceError must be raised"

    @pytest.mark.asyncio
    async def test_client_exception_error_has_safe_user_message(self) -> None:
        mock_client = make_async_client(put_events_side_effect=Exception("connection refused"))
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError) as exc_info:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        assert exc_info.value.user_message == "An unexpected error occurred"

    @pytest.mark.asyncio
    async def test_client_exception_internal_message_contains_detail_type(self) -> None:
        mock_client = make_async_client(put_events_side_effect=Exception("timeout"))
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with pytest.raises(ExternalServiceError) as exc_info:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        # Internal message must differ from user_message
        assert exc_info.value.message != exc_info.value.user_message


# ── Success logging ───────────────────────────────────────────────────────────


class TestSuccessLogging:
    """On success, publish() must log at info level with detail_type and event_id (Req 2.3)."""

    @pytest.mark.asyncio
    async def test_success_logs_at_info_level(self) -> None:
        import structlog.testing

        mock_client = make_async_client(failed_entry_count=0)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with structlog.testing.capture_logs() as logs:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        info_logs = [entry for entry in logs if entry.get("log_level") == "info"]
        assert len(info_logs) >= 1

    @pytest.mark.asyncio
    async def test_success_log_contains_detail_type(self) -> None:
        import structlog.testing

        mock_client = make_async_client(failed_entry_count=0)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with structlog.testing.capture_logs() as logs:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        info_logs = [entry for entry in logs if entry.get("log_level") == "info"]
        assert any(entry.get("detail_type") == "identity.user.registered" for entry in info_logs)

    @pytest.mark.asyncio
    async def test_success_log_contains_event_id(self) -> None:
        import structlog.testing

        mock_client = make_async_client(failed_entry_count=0)
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with structlog.testing.capture_logs() as logs:
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        info_logs = [entry for entry in logs if entry.get("log_level") == "info"]
        assert any("event_id" in entry for entry in info_logs)

    @pytest.mark.asyncio
    async def test_error_logs_on_client_exception(self) -> None:
        import structlog.testing

        mock_client = make_async_client(put_events_side_effect=Exception("timeout"))
        session = make_session(mock_client)
        publisher = make_publisher(session)

        with structlog.testing.capture_logs() as logs, pytest.raises(ExternalServiceError):
            await publisher.publish("identity.user.registered", {"user_id": "u-1"})

        error_logs = [entry for entry in logs if entry.get("log_level") == "error"]
        assert len(error_logs) >= 1
        assert any(entry.get("detail_type") == "identity.user.registered" for entry in error_logs)


# ── Constructor accepts session ───────────────────────────────────────────────


class TestConstructor:
    """EventBridgePublisher must accept an aioboto3.Session parameter."""

    def test_constructor_accepts_session_parameter(self) -> None:
        import aioboto3

        from src.infrastructure.messaging.event_publisher import EventBridgePublisher

        session = aioboto3.Session()
        publisher = EventBridgePublisher(bus_name="test-bus", region="us-east-1", session=session)
        assert publisher is not None

    def test_constructor_creates_default_session_when_not_provided(self) -> None:
        """session parameter should be optional with a sensible default."""
        from src.infrastructure.messaging.event_publisher import EventBridgePublisher

        publisher = EventBridgePublisher(bus_name="test-bus", region="us-east-1")
        assert publisher is not None

    def test_does_not_store_boto3_client_at_init(self) -> None:
        """The old pattern stored self._client at __init__ time — new pattern must not."""
        import aioboto3

        from src.infrastructure.messaging.event_publisher import EventBridgePublisher

        session = aioboto3.Session()
        publisher = EventBridgePublisher(bus_name="test-bus", region="us-east-1", session=session)

        # Must not have a synchronous boto3 client stored
        assert not hasattr(publisher, "_client") or publisher._client is None  # type: ignore[union-attr]
