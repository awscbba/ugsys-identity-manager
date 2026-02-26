"""Integration tests for DynamoDBOutboxRepository — moto-backed DynamoDB.

Tests cover:
- save() + find_pending() round-trip
- increment_retry() atomic counter across multiple calls
- mark_published() and mark_failed() state transitions
- Backward compatibility: items missing optional fields deserialize with safe defaults
- ClientError wrapping: RepositoryError raised, not raw ClientError
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.entities.outbox_event import OutboxEvent
from src.domain.exceptions import RepositoryError
from src.infrastructure.persistence.dynamodb_outbox_repository import DynamoDBOutboxRepository

_OUTBOX_TABLE = "ugsys-outbox-identity-test"
_REGION = "us-east-1"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _create_outbox_table(region: str = _REGION) -> None:
    """Create the outbox table with StatusIndex GSI using sync boto3."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    dynamodb.create_table(
        TableName=_OUTBOX_TABLE,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "StatusIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _make_event(
    event_id: str = "01JTEST000000000000000001",
    status: str = "pending",
    retry_count: int = 0,
    published_at: str | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        id=event_id,
        aggregate_type="User",
        aggregate_id="user-123",
        event_type="identity.user.registered",
        payload=json.dumps({"user_id": "user-123"}),
        created_at="2026-02-26T10:00:00+00:00",
        status=status,
        retry_count=retry_count,
        published_at=published_at,
    )


@pytest.fixture()
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def outbox_table(aws_credentials: None) -> object:
    with mock_aws():
        _create_outbox_table()
        yield


@pytest.fixture()
def repo(outbox_table: object) -> DynamoDBOutboxRepository:
    import aioboto3
    return DynamoDBOutboxRepository(
        table_name=_OUTBOX_TABLE,
        region=_REGION,
        session=aioboto3.Session(),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_find_pending_round_trip(repo: DynamoDBOutboxRepository) -> None:
    """save() persists the event; find_pending() returns it with status=pending."""
    event = _make_event()

    await repo.save(event)
    results = await repo.find_pending(limit=10)

    assert len(results) == 1
    found = results[0]
    assert found.id == event.id
    assert found.aggregate_type == event.aggregate_type
    assert found.aggregate_id == event.aggregate_id
    assert found.event_type == event.event_type
    assert found.payload == event.payload
    assert found.created_at == event.created_at
    assert found.status == "pending"
    assert found.retry_count == 0
    assert found.published_at is None


@pytest.mark.asyncio
async def test_save_forces_pending_status(repo: DynamoDBOutboxRepository) -> None:
    """save() always stores status='pending' regardless of the event's status field."""
    event = _make_event(status="published")

    await repo.save(event)
    results = await repo.find_pending(limit=10)

    assert len(results) == 1
    assert results[0].status == "pending"


@pytest.mark.asyncio
async def test_find_pending_excludes_published_and_failed(repo: DynamoDBOutboxRepository) -> None:
    """find_pending() returns only events with status='pending'."""
    pending = _make_event(event_id="01JTEST000000000000000001")
    await repo.save(pending)

    # Save a second event then mark it published
    to_publish = _make_event(event_id="01JTEST000000000000000002")
    await repo.save(to_publish)
    await repo.mark_published(to_publish.id)

    # Save a third event then mark it failed
    to_fail = _make_event(event_id="01JTEST000000000000000003")
    await repo.save(to_fail)
    await repo.mark_failed(to_fail.id)

    results = await repo.find_pending(limit=10)

    assert len(results) == 1
    assert results[0].id == pending.id


@pytest.mark.asyncio
async def test_mark_published_sets_status_and_timestamp(repo: DynamoDBOutboxRepository) -> None:
    """mark_published() sets status='published' and a non-empty published_at timestamp."""
    event = _make_event()
    await repo.save(event)

    before = datetime.now(UTC).isoformat()
    await repo.mark_published(event.id)
    after = datetime.now(UTC).isoformat()

    # Fetch the item directly to inspect all fields
    client = boto3.client("dynamodb", region_name=_REGION)
    response = client.get_item(
        TableName=_OUTBOX_TABLE,
        Key={
            "PK": {"S": f"OUTBOX#{event.id}"},
            "SK": {"S": "EVENT"},
        },
    )
    item = response["Item"]
    assert item["status"]["S"] == "published"
    published_at = item["published_at"]["S"]
    assert published_at >= before
    assert published_at <= after


@pytest.mark.asyncio
async def test_mark_failed_sets_status(repo: DynamoDBOutboxRepository) -> None:
    """mark_failed() sets status='failed'."""
    event = _make_event()
    await repo.save(event)

    await repo.mark_failed(event.id)

    client = boto3.client("dynamodb", region_name=_REGION)
    response = client.get_item(
        TableName=_OUTBOX_TABLE,
        Key={
            "PK": {"S": f"OUTBOX#{event.id}"},
            "SK": {"S": "EVENT"},
        },
    )
    assert response["Item"]["status"]["S"] == "failed"


@pytest.mark.asyncio
async def test_increment_retry_atomic_counter(repo: DynamoDBOutboxRepository) -> None:
    """increment_retry() atomically increments retry_count; two calls go 0→1→2."""
    event = _make_event()
    await repo.save(event)

    await repo.increment_retry(event.id)
    await repo.increment_retry(event.id)

    client = boto3.client("dynamodb", region_name=_REGION)
    response = client.get_item(
        TableName=_OUTBOX_TABLE,
        Key={
            "PK": {"S": f"OUTBOX#{event.id}"},
            "SK": {"S": "EVENT"},
        },
    )
    assert int(response["Item"]["retry_count"]["N"]) == 2


@pytest.mark.asyncio
async def test_backward_compat_missing_optional_fields(repo: DynamoDBOutboxRepository) -> None:
    """Items missing published_at and with no status/retry_count deserialize with safe defaults."""
    # Write a minimal item directly (simulating an old schema item)
    client = boto3.client("dynamodb", region_name=_REGION)
    event_id = "01JTEST000000000000000099"
    client.put_item(
        TableName=_OUTBOX_TABLE,
        Item={
            "PK": {"S": f"OUTBOX#{event_id}"},
            "SK": {"S": "EVENT"},
            "id": {"S": event_id},
            "aggregate_type": {"S": "User"},
            "aggregate_id": {"S": "user-old"},
            "event_type": {"S": "identity.user.registered"},
            "payload": {"S": "{}"},
            "created_at": {"S": "2026-01-01T00:00:00+00:00"},
            "status": {"S": "pending"},
            # NOTE: no published_at, no retry_count
        },
    )

    results = await repo.find_pending(limit=10)

    assert len(results) == 1
    found = results[0]
    assert found.published_at is None
    assert found.retry_count == 0
    assert found.status == "pending"


@pytest.mark.asyncio
async def test_client_error_raises_repository_error(repo: DynamoDBOutboxRepository) -> None:
    """Any ClientError from DynamoDB is wrapped in RepositoryError, not propagated raw."""
    # Patch the aioboto3 client's put_item to raise a ClientError
    error_response = {
        "Error": {"Code": "InternalServerError", "Message": "Simulated DynamoDB failure"}
    }

    async def _raise_client_error(*args: object, **kwargs: object) -> None:
        raise ClientError(error_response, "PutItem")

    mock_client = AsyncMock()
    mock_client.put_item = _raise_client_error
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Temporarily override _test_client so _get_client() yields our mock
    repo._test_client = mock_client  # type: ignore[attr-defined]

    with pytest.raises(RepositoryError) as exc_info:
        await repo.save(_make_event())

    assert exc_info.value.error_code == "REPOSITORY_ERROR"
    assert "An unexpected error occurred" == exc_info.value.user_message
    # Internal message must NOT be exposed as user_message
    assert exc_info.value.message != exc_info.value.user_message
