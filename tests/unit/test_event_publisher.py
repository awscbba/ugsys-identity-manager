"""Unit tests for EventBridgePublisher infrastructure adapter.

Updated to cover the aioboto3 async implementation.
The old synchronous boto3 tests have been replaced — the publisher now uses
an async context manager per publish() call instead of a stored self._client.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.exceptions import ExternalServiceError
from src.infrastructure.messaging.event_publisher import EventBridgePublisher

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_async_client(*, failed_entry_count: int = 0) -> AsyncMock:
    client = AsyncMock()
    client.put_events = AsyncMock(
        return_value={
            "FailedEntryCount": failed_entry_count,
            "Entries": [{"EventId": "evt-001"}],
        }
    )
    return client


def make_session(mock_client: AsyncMock) -> MagicMock:
    session = MagicMock()

    @asynccontextmanager
    async def _client_ctx(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield mock_client

    session.client = MagicMock(side_effect=_client_ctx)
    return session


@pytest.fixture
def mock_client() -> AsyncMock:
    return make_async_client()


@pytest.fixture
def publisher(mock_client: AsyncMock) -> EventBridgePublisher:
    session = make_session(mock_client)
    return EventBridgePublisher(bus_name="test-bus", region="us-east-1", session=session)


# ── Core publish behaviour ────────────────────────────────────────────────────


async def test_publish_calls_put_events(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    await publisher.publish(
        detail_type="identity.user.registered",
        payload={"user_id": "abc-123", "email": "test@example.com"},
    )

    mock_client.put_events.assert_awaited_once()
    call_kwargs = mock_client.put_events.call_args[1]
    entries = call_kwargs["Entries"]
    assert len(entries) == 1
    assert entries[0]["EventBusName"] == "test-bus"
    assert entries[0]["Source"] == "ugsys.identity-manager"
    assert entries[0]["DetailType"] == "identity.user.registered"


async def test_publish_envelope_contains_payload(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    payload = {"user_id": "xyz", "email": "a@b.com"}
    await publisher.publish(detail_type="identity.user.activated", payload=payload)

    detail_str = mock_client.put_events.call_args[1]["Entries"][0]["Detail"]
    envelope = json.loads(detail_str)

    assert envelope["payload"] == payload
    assert "event_id" in envelope
    assert "timestamp" in envelope
    assert envelope["event_version"] == "1.0"


async def test_publish_envelope_includes_correlation_id(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    from src.presentation.middleware.correlation_id import correlation_id_var

    token = correlation_id_var.set("my-trace-id")
    try:
        await publisher.publish(detail_type="identity.auth.login_success", payload={})
        detail_str = mock_client.put_events.call_args[1]["Entries"][0]["Detail"]
        envelope = json.loads(detail_str)
        assert envelope["correlation_id"] == "my-trace-id"
    finally:
        correlation_id_var.reset(token)


async def test_publish_raises_on_client_error(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    """Errors must now propagate as ExternalServiceError — not be swallowed."""
    mock_client.put_events = AsyncMock(side_effect=Exception("EventBridge unavailable"))

    with pytest.raises(ExternalServiceError):
        await publisher.publish(detail_type="identity.user.registered", payload={"user_id": "1"})


async def test_publish_raises_on_failed_entry_count(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    mock_client.put_events = AsyncMock(
        return_value={"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalFailure"}]}
    )

    with pytest.raises(ExternalServiceError):
        await publisher.publish(detail_type="identity.user.registered", payload={"user_id": "1"})


async def test_publish_event_id_is_unique(
    publisher: EventBridgePublisher, mock_client: AsyncMock
) -> None:
    await publisher.publish(detail_type="evt.a", payload={})
    await publisher.publish(detail_type="evt.b", payload={})

    calls = mock_client.put_events.call_args_list
    id1 = json.loads(calls[0][1]["Entries"][0]["Detail"])["event_id"]
    id2 = json.loads(calls[1][1]["Entries"][0]["Detail"])["event_id"]
    assert id1 != id2
