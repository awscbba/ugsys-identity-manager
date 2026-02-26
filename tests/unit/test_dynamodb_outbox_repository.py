"""Unit tests for DynamoDBOutboxRepository.

TDD: RED phase — tests written before implementation.
All tests mock the aioboto3 client at the port boundary.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from src.domain.entities.outbox_event import OutboxEvent
from src.domain.exceptions import RepositoryError
from src.domain.repositories.unit_of_work import TransactionalOperation

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_event(
    *,
    id: str = "01JXXX000000000000000000",
    aggregate_type: str = "User",
    aggregate_id: str = "user-abc-123",
    event_type: str = "identity.user.registered",
    payload: str = '{"user_id": "user-abc-123"}',
    created_at: str = "2025-01-01T00:00:00+00:00",
    status: str = "pending",
    retry_count: int = 0,
    published_at: str | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        id=id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        created_at=created_at,
        status=status,
        retry_count=retry_count,
        published_at=published_at,
    )


def make_client_error(code: str = "InternalServerError") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "test error"}},
        operation_name="TestOperation",
    )


def make_repo(mock_client: Any) -> Any:
    """Create a DynamoDBOutboxRepository with a pre-wired mock client."""
    from src.infrastructure.persistence.dynamodb_outbox_repository import DynamoDBOutboxRepository

    repo = DynamoDBOutboxRepository.__new__(DynamoDBOutboxRepository)
    repo._table_name = "ugsys-outbox-identity-test"
    repo._region = "us-east-1"
    repo._client = mock_client
    return repo


# ── Serialization round-trip ──────────────────────────────────────────────────


class TestToItemFromItemRoundTrip:
    """_to_item / _from_item must be inverse operations for all fields."""

    def test_round_trip_all_fields_present(self) -> None:

        repo = make_repo(MagicMock())
        event = make_event(
            id="01JYYY",
            aggregate_type="User",
            aggregate_id="u-999",
            event_type="identity.user.deactivated",
            payload='{"user_id": "u-999"}',
            created_at="2025-06-01T12:00:00+00:00",
            status="published",
            retry_count=3,
            published_at="2025-06-01T12:05:00+00:00",
        )
        item = repo._to_item(event)
        restored = repo._from_item(item)

        assert restored.id == event.id
        assert restored.aggregate_type == event.aggregate_type
        assert restored.aggregate_id == event.aggregate_id
        assert restored.event_type == event.event_type
        assert restored.payload == event.payload
        assert restored.created_at == event.created_at
        assert restored.status == event.status
        assert restored.retry_count == event.retry_count
        assert restored.published_at == event.published_at

    def test_round_trip_without_published_at(self) -> None:

        repo = make_repo(MagicMock())
        event = make_event(published_at=None)
        item = repo._to_item(event)
        restored = repo._from_item(item)

        assert restored.published_at is None

    def test_to_item_produces_attribute_value_dicts(self) -> None:
        """_to_item must produce low-level DynamoDB AttributeValue format."""

        repo = make_repo(MagicMock())
        event = make_event()
        item = repo._to_item(event)

        # PK and SK must be AttributeValue dicts
        assert item["PK"] == {"S": f"OUTBOX#{event.id}"}
        assert item["SK"] == {"S": "EVENT"}
        assert item["id"] == {"S": event.id}
        assert item["status"] == {"S": "pending"}
        assert item["retry_count"] == {"N": "0"}

    def test_to_item_omits_published_at_when_none(self) -> None:

        repo = make_repo(MagicMock())
        event = make_event(published_at=None)
        item = repo._to_item(event)

        assert "published_at" not in item

    def test_to_item_includes_published_at_when_set(self) -> None:

        repo = make_repo(MagicMock())
        event = make_event(published_at="2025-06-01T12:05:00+00:00")
        item = repo._to_item(event)

        assert item["published_at"] == {"S": "2025-06-01T12:05:00+00:00"}

    def test_from_item_uses_safe_defaults_for_missing_optional_fields(self) -> None:
        """_from_item must handle items missing optional fields (backward compat)."""

        repo = make_repo(MagicMock())
        # Minimal item — no status, retry_count, or published_at
        minimal_item = {
            "PK": {"S": "OUTBOX#01JXXX"},
            "SK": {"S": "EVENT"},
            "id": {"S": "01JXXX"},
            "aggregate_type": {"S": "User"},
            "aggregate_id": {"S": "u-1"},
            "event_type": {"S": "identity.user.registered"},
            "payload": {"S": "{}"},
            "created_at": {"S": "2025-01-01T00:00:00+00:00"},
        }
        event = repo._from_item(minimal_item)

        assert event.status == "pending"
        assert event.retry_count == 0
        assert event.published_at is None


# ── save() ────────────────────────────────────────────────────────────────────


class TestSave:
    """save() must call put_item with ConditionExpression and force pending/0."""

    @pytest.mark.asyncio
    async def test_save_calls_put_item(self) -> None:
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)
        event = make_event()

        await repo.save(event)

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_uses_condition_expression(self) -> None:
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)
        event = make_event()

        await repo.save(event)

        call_kwargs = mock_client.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(PK)"

    @pytest.mark.asyncio
    async def test_save_forces_status_pending(self) -> None:
        """save() must write status='pending' regardless of input status."""
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)
        # Pass an event with status="published" — save must override to "pending"
        event = make_event(status="published")

        await repo.save(event)

        call_kwargs = mock_client.put_item.call_args[1]
        item = call_kwargs["Item"]
        assert item["status"] == {"S": "pending"}

    @pytest.mark.asyncio
    async def test_save_forces_retry_count_zero(self) -> None:
        """save() must write retry_count=0 regardless of input retry_count."""
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)
        event = make_event(retry_count=5)

        await repo.save(event)

        call_kwargs = mock_client.put_item.call_args[1]
        item = call_kwargs["Item"]
        assert item["retry_count"] == {"N": "0"}

    @pytest.mark.asyncio
    async def test_save_returns_event(self) -> None:
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)
        event = make_event()

        result = await repo.save(event)

        assert result.id == event.id

    @pytest.mark.asyncio
    async def test_save_client_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(side_effect=make_client_error("InternalServerError"))
        repo = make_repo(mock_client)
        event = make_event()

        with pytest.raises(RepositoryError):
            await repo.save(event)

    @pytest.mark.asyncio
    async def test_save_does_not_propagate_raw_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(
            side_effect=make_client_error("ProvisionedThroughputExceededException")
        )
        repo = make_repo(mock_client)
        event = make_event()

        with pytest.raises(RepositoryError):
            await repo.save(event)

        # Ensure it's NOT a raw ClientError
        try:
            await repo.save(event)
        except RepositoryError:
            pass
        except ClientError:
            pytest.fail("Raw ClientError must not propagate — must be wrapped in RepositoryError")


# ── save_operation() ──────────────────────────────────────────────────────────


class TestSaveOperation:
    """save_operation() must return a TransactionalOperation without calling put_item."""

    def test_save_operation_returns_transactional_operation(self) -> None:
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event()

        result = repo.save_operation(event)

        assert isinstance(result, TransactionalOperation)

    def test_save_operation_has_put_operation_type(self) -> None:
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event()

        result = repo.save_operation(event)

        assert result.operation_type == "Put"

    def test_save_operation_includes_table_name(self) -> None:
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event()

        result = repo.save_operation(event)

        assert result.params["TableName"] == "ugsys-outbox-identity-test"

    def test_save_operation_includes_condition_expression(self) -> None:
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event()

        result = repo.save_operation(event)

        assert result.params["ConditionExpression"] == "attribute_not_exists(PK)"

    def test_save_operation_does_not_call_put_item(self) -> None:
        """save_operation is synchronous — must NOT perform any I/O."""
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event()

        repo.save_operation(event)

        mock_client.put_item.assert_not_called()

    def test_save_operation_is_synchronous(self) -> None:
        """save_operation must not be a coroutine."""
        import inspect

        from src.infrastructure.persistence.dynamodb_outbox_repository import (
            DynamoDBOutboxRepository,
        )

        assert not inspect.iscoroutinefunction(DynamoDBOutboxRepository.save_operation)

    def test_save_operation_item_has_attribute_value_format(self) -> None:
        mock_client = MagicMock()
        repo = make_repo(mock_client)
        event = make_event(id="01JZZZ")

        result = repo.save_operation(event)

        item = result.params["Item"]
        assert item["PK"] == {"S": "OUTBOX#01JZZZ"}
        assert item["SK"] == {"S": "EVENT"}


# ── mark_published() ──────────────────────────────────────────────────────────


class TestMarkPublished:
    """mark_published() must set status='published' and published_at to UTC ISO 8601."""

    @pytest.mark.asyncio
    async def test_mark_published_calls_update_item(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_published("01JXXX")

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_published_sets_status_published(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_published("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        # The update expression must set status to "published"
        expr_values = call_kwargs.get("ExpressionAttributeValues", {})
        status_values = [v for v in expr_values.values() if v == {"S": "published"}]
        assert len(status_values) >= 1, "status='published' must be in ExpressionAttributeValues"

    @pytest.mark.asyncio
    async def test_mark_published_sets_published_at_utc_iso8601(self) -> None:
        """published_at must be a UTC ISO 8601 timestamp."""
        from datetime import UTC, datetime

        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        before = datetime.now(UTC).isoformat()
        await repo.mark_published("01JXXX")
        after = datetime.now(UTC).isoformat()

        call_kwargs = mock_client.update_item.call_args[1]
        expr_values = call_kwargs.get("ExpressionAttributeValues", {})
        # Find the published_at value — it should be a string between before and after
        ts_values = [
            v["S"]
            for v in expr_values.values()
            if isinstance(v, dict) and "S" in v and v["S"] != "published"
        ]
        assert len(ts_values) >= 1, "published_at timestamp must be in ExpressionAttributeValues"
        ts = ts_values[0]
        assert before <= ts <= after, f"Timestamp {ts!r} not in range [{before!r}, {after!r}]"

    @pytest.mark.asyncio
    async def test_mark_published_uses_correct_key(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_published("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        key = call_kwargs["Key"]
        assert key["PK"] == {"S": "OUTBOX#01JXXX"}
        assert key["SK"] == {"S": "EVENT"}

    @pytest.mark.asyncio
    async def test_mark_published_client_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error())
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.mark_published("01JXXX")


# ── increment_retry() ─────────────────────────────────────────────────────────


class TestIncrementRetry:
    """increment_retry() must use an atomic ADD expression."""

    @pytest.mark.asyncio
    async def test_increment_retry_calls_update_item(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.increment_retry("01JXXX")

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment_retry_uses_add_expression(self) -> None:
        """Must use ADD for atomic counter — not SET."""
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.increment_retry("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        update_expr = call_kwargs.get("UpdateExpression", "")
        assert "ADD" in update_expr.upper(), f"Expected ADD expression, got: {update_expr!r}"

    @pytest.mark.asyncio
    async def test_increment_retry_adds_one(self) -> None:
        """The ADD value must be exactly 1."""
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.increment_retry("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        expr_values = call_kwargs.get("ExpressionAttributeValues", {})
        one_values = [v for v in expr_values.values() if v == {"N": "1"}]
        assert len(one_values) >= 1, "ADD value of 1 must be in ExpressionAttributeValues"

    @pytest.mark.asyncio
    async def test_increment_retry_uses_correct_key(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.increment_retry("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        key = call_kwargs["Key"]
        assert key["PK"] == {"S": "OUTBOX#01JXXX"}
        assert key["SK"] == {"S": "EVENT"}

    @pytest.mark.asyncio
    async def test_increment_retry_client_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error())
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.increment_retry("01JXXX")


# ── mark_failed() ─────────────────────────────────────────────────────────────


class TestMarkFailed:
    """mark_failed() must set status='failed'."""

    @pytest.mark.asyncio
    async def test_mark_failed_calls_update_item(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_failed("01JXXX")

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_failed_sets_status_failed(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_failed("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        expr_values = call_kwargs.get("ExpressionAttributeValues", {})
        failed_values = [v for v in expr_values.values() if v == {"S": "failed"}]
        assert len(failed_values) >= 1, "status='failed' must be in ExpressionAttributeValues"

    @pytest.mark.asyncio
    async def test_mark_failed_uses_correct_key(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={})
        repo = make_repo(mock_client)

        await repo.mark_failed("01JXXX")

        call_kwargs = mock_client.update_item.call_args[1]
        key = call_kwargs["Key"]
        assert key["PK"] == {"S": "OUTBOX#01JXXX"}
        assert key["SK"] == {"S": "EVENT"}

    @pytest.mark.asyncio
    async def test_mark_failed_client_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error())
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.mark_failed("01JXXX")


# ── find_pending() ────────────────────────────────────────────────────────────


class TestFindPending:
    """find_pending() must query StatusIndex GSI with status='pending'."""

    @pytest.mark.asyncio
    async def test_find_pending_queries_status_index(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})
        repo = make_repo(mock_client)

        await repo.find_pending(limit=10)

        mock_client.query.assert_called_once()
        call_kwargs = mock_client.query.call_args[1]
        assert call_kwargs.get("IndexName") == "StatusIndex"

    @pytest.mark.asyncio
    async def test_find_pending_filters_by_pending_status(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})
        repo = make_repo(mock_client)

        await repo.find_pending(limit=10)

        call_kwargs = mock_client.query.call_args[1]
        expr_values = call_kwargs.get("ExpressionAttributeValues", {})
        pending_values = [v for v in expr_values.values() if v == {"S": "pending"}]
        assert len(pending_values) >= 1, "Query must filter by status='pending'"

    @pytest.mark.asyncio
    async def test_find_pending_respects_limit(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})
        repo = make_repo(mock_client)

        await repo.find_pending(limit=25)

        call_kwargs = mock_client.query.call_args[1]
        assert call_kwargs.get("Limit") == 25

    @pytest.mark.asyncio
    async def test_find_pending_returns_empty_list_when_no_items(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})
        repo = make_repo(mock_client)

        result = await repo.find_pending(limit=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_find_pending_returns_deserialized_events(self) -> None:
        event = make_event(id="01JAAA", status="pending")
        mock_client = AsyncMock()

        # Build a raw DynamoDB item from the event
        tmp_repo = make_repo(MagicMock())
        raw_item = tmp_repo._to_item(event)

        mock_client.query = AsyncMock(return_value={"Items": [raw_item]})
        repo = make_repo(mock_client)

        result = await repo.find_pending(limit=10)

        assert len(result) == 1
        assert result[0].id == "01JAAA"
        assert result[0].status == "pending"

    @pytest.mark.asyncio
    async def test_find_pending_client_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(side_effect=make_client_error())
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.find_pending(limit=10)


# ── ClientError wrapping ──────────────────────────────────────────────────────


class TestClientErrorWrapping:
    """All ClientErrors must be wrapped in RepositoryError — never propagated raw."""

    @pytest.mark.asyncio
    async def test_save_wraps_any_client_error(self) -> None:
        for code in [
            "InternalServerError",
            "ProvisionedThroughputExceededException",
            "ServiceUnavailable",
        ]:
            mock_client = AsyncMock()
            mock_client.put_item = AsyncMock(side_effect=make_client_error(code))
            repo = make_repo(mock_client)

            with pytest.raises(RepositoryError):
                await repo.save(make_event())

    @pytest.mark.asyncio
    async def test_mark_published_wraps_any_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error("ThrottlingException"))
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.mark_published("01JXXX")

    @pytest.mark.asyncio
    async def test_increment_retry_wraps_any_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error("ThrottlingException"))
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.increment_retry("01JXXX")

    @pytest.mark.asyncio
    async def test_mark_failed_wraps_any_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(side_effect=make_client_error("ThrottlingException"))
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.mark_failed("01JXXX")

    @pytest.mark.asyncio
    async def test_find_pending_wraps_any_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(side_effect=make_client_error("ThrottlingException"))
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError):
            await repo.find_pending(limit=10)

    @pytest.mark.asyncio
    async def test_repository_error_has_safe_user_message(self) -> None:
        """RepositoryError user_message must never expose internal details."""
        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock(side_effect=make_client_error("InternalServerError"))
        repo = make_repo(mock_client)

        with pytest.raises(RepositoryError) as exc_info:
            await repo.save(make_event())

        assert exc_info.value.user_message == "An unexpected error occurred"
        # Internal message must NOT be the same as user_message
        assert exc_info.value.message != exc_info.value.user_message
