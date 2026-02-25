"""Unit tests for EventBridgePublisher infrastructure adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.messaging.event_publisher import EventBridgePublisher


@pytest.fixture
def mock_boto_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def publisher(mock_boto_client: MagicMock) -> EventBridgePublisher:
    patch_target = "src.infrastructure.messaging.event_publisher.boto3.client"
    with patch(patch_target, return_value=mock_boto_client):
        return EventBridgePublisher(bus_name="test-bus", region="us-east-1")


async def test_publish_calls_put_events(
    publisher: EventBridgePublisher, mock_boto_client: MagicMock
) -> None:
    # Act
    await publisher.publish(
        detail_type="identity.user.registered",
        payload={"user_id": "abc-123", "email": "test@example.com"},
    )

    # Assert
    mock_boto_client.put_events.assert_called_once()
    call_args = mock_boto_client.put_events.call_args
    entries = call_args.kwargs["Entries"]
    assert len(entries) == 1
    assert entries[0]["EventBusName"] == "test-bus"
    assert entries[0]["Source"] == "ugsys.identity-manager"
    assert entries[0]["DetailType"] == "identity.user.registered"


async def test_publish_envelope_contains_payload(
    publisher: EventBridgePublisher, mock_boto_client: MagicMock
) -> None:
    import json

    payload = {"user_id": "xyz", "email": "a@b.com"}
    await publisher.publish(detail_type="identity.user.activated", payload=payload)

    detail_str = mock_boto_client.put_events.call_args.kwargs["Entries"][0]["Detail"]
    envelope = json.loads(detail_str)

    assert envelope["payload"] == payload
    assert "event_id" in envelope
    assert "timestamp" in envelope
    assert envelope["event_version"] == "1.0"


async def test_publish_envelope_includes_correlation_id(
    publisher: EventBridgePublisher, mock_boto_client: MagicMock
) -> None:
    import json

    from src.presentation.middleware.correlation_id import correlation_id_var

    token = correlation_id_var.set("my-trace-id")
    try:
        await publisher.publish(detail_type="identity.auth.login_success", payload={})
        detail_str = mock_boto_client.put_events.call_args.kwargs["Entries"][0]["Detail"]
        envelope = json.loads(detail_str)
        assert envelope["correlation_id"] == "my-trace-id"
    finally:
        correlation_id_var.reset(token)


async def test_publish_does_not_raise_on_boto_error(
    publisher: EventBridgePublisher, mock_boto_client: MagicMock
) -> None:
    """EventBridge failures must be swallowed — never crash the caller."""
    mock_boto_client.put_events.side_effect = Exception("EventBridge unavailable")

    # Should not raise
    await publisher.publish(detail_type="identity.user.registered", payload={"user_id": "1"})


async def test_publish_event_id_is_unique(
    publisher: EventBridgePublisher, mock_boto_client: MagicMock
) -> None:
    import json

    await publisher.publish(detail_type="evt.a", payload={})
    await publisher.publish(detail_type="evt.b", payload={})

    calls = mock_boto_client.put_events.call_args_list
    id1 = json.loads(calls[0].kwargs["Entries"][0]["Detail"])["event_id"]
    id2 = json.loads(calls[1].kwargs["Entries"][0]["Detail"])["event_id"]
    assert id1 != id2
