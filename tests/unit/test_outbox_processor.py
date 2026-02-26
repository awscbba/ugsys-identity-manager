"""Unit tests for OutboxProcessor application service.

TDD: RED phase — tests written before implementation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.domain.entities.outbox_event import OutboxEvent
from src.domain.exceptions import ExternalServiceError
from src.domain.repositories.event_publisher import EventPublisher
from src.domain.repositories.outbox_repository import OutboxRepository

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_event(
    event_id: str = "01JXXX001",
    event_type: str = "identity.user.registered",
    retry_count: int = 0,
    status: str = "pending",
) -> OutboxEvent:
    return OutboxEvent(
        id=event_id,
        aggregate_type="User",
        aggregate_id="user-001",
        event_type=event_type,
        payload=json.dumps({"user_id": "user-001"}),
        created_at=datetime.now(UTC).isoformat(),
        status=status,
        retry_count=retry_count,
    )


def make_processor(
    outbox_repo: OutboxRepository | None = None,
    publisher: EventPublisher | None = None,
) -> object:
    from src.application.services.outbox_processor import OutboxProcessor

    return OutboxProcessor(
        outbox_repo=outbox_repo or AsyncMock(spec=OutboxRepository),
        publisher=publisher or AsyncMock(spec=EventPublisher),
    )


# ── find_pending is called with batch_size ────────────────────────────────────


class TestProcessPendingFetchesBatch:
    @pytest.mark.asyncio
    async def test_calls_find_pending_with_default_batch_size(self) -> None:
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = []
        proc = make_processor(outbox_repo=outbox_repo)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.find_pending.assert_awaited_once_with(limit=25)

    @pytest.mark.asyncio
    async def test_calls_find_pending_with_custom_batch_size(self) -> None:
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = []
        proc = make_processor(outbox_repo=outbox_repo)

        await proc.process_pending(batch_size=10)  # type: ignore[attr-defined]

        outbox_repo.find_pending.assert_awaited_once_with(limit=10)


# ── Successful publish path ───────────────────────────────────────────────────


class TestSuccessfulPublish:
    @pytest.mark.asyncio
    async def test_successful_publish_calls_mark_published(self) -> None:
        event = make_event(event_id="evt-001")
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.mark_published.assert_awaited_once_with("evt-001")

    @pytest.mark.asyncio
    async def test_successful_publish_does_not_call_increment_retry(self) -> None:
        event = make_event()
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.increment_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_publish_increments_return_count(self) -> None:
        events = [make_event(event_id=f"evt-{i:03d}") for i in range(3)]
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = events
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 3

    @pytest.mark.asyncio
    async def test_publish_called_with_correct_event_type_and_payload(self) -> None:
        payload_dict = {"user_id": "user-001", "email": "dev@example.com"}
        event = make_event(event_type="identity.user.registered")
        event.payload = json.dumps(payload_dict)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        publisher.publish.assert_awaited_once_with("identity.user.registered", payload_dict)


# ── Failed publish path ───────────────────────────────────────────────────────


class TestFailedPublish:
    @pytest.mark.asyncio
    async def test_failed_publish_calls_increment_retry(self) -> None:
        event = make_event(event_id="evt-fail")
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        publisher.publish.side_effect = ExternalServiceError(
            message="EventBridge failed",
            user_message="An unexpected error occurred",
        )
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.increment_retry.assert_awaited_once_with("evt-fail")

    @pytest.mark.asyncio
    async def test_failed_publish_does_not_call_mark_published(self) -> None:
        event = make_event()
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        publisher.publish.side_effect = ExternalServiceError(
            message="EventBridge failed",
            user_message="An unexpected error occurred",
        )
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.mark_published.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_publish_not_counted_in_return_value(self) -> None:
        events = [make_event(event_id=f"evt-{i:03d}") for i in range(3)]
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = events
        publisher = AsyncMock(spec=EventPublisher)
        publisher.publish.side_effect = ExternalServiceError(
            message="EventBridge failed",
            user_message="An unexpected error occurred",
        )
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 0

    @pytest.mark.asyncio
    async def test_one_failure_does_not_stop_processing_remaining_events(self) -> None:
        """A failed event should not abort the loop — remaining events are still processed."""
        fail_event = make_event(event_id="evt-fail")
        ok_event = make_event(event_id="evt-ok")
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [fail_event, ok_event]
        publisher = AsyncMock(spec=EventPublisher)
        publisher.publish.side_effect = [
            ExternalServiceError(message="fail", user_message="err"),
            None,  # second call succeeds
        ]
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 1
        outbox_repo.increment_retry.assert_awaited_once_with("evt-fail")
        outbox_repo.mark_published.assert_awaited_once_with("evt-ok")


# ── Max-retry threshold ───────────────────────────────────────────────────────


class TestMaxRetryThreshold:
    @pytest.mark.asyncio
    async def test_event_at_retry_5_calls_mark_failed(self) -> None:
        event = make_event(event_id="evt-maxretry", retry_count=5)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.mark_failed.assert_awaited_once_with("evt-maxretry")

    @pytest.mark.asyncio
    async def test_event_at_retry_5_does_not_call_publish(self) -> None:
        event = make_event(retry_count=5)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_at_retry_5_not_counted_in_return_value(self) -> None:
        event = make_event(retry_count=5)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 0

    @pytest.mark.asyncio
    async def test_event_above_retry_5_also_calls_mark_failed(self) -> None:
        """retry_count > 5 should also be treated as max-retry."""
        event = make_event(retry_count=7)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        outbox_repo.mark_failed.assert_awaited_once()
        publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_at_retry_4_still_attempts_publish(self) -> None:
        """retry_count=4 is below threshold — should still attempt delivery."""
        event = make_event(retry_count=4)
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [event]
        publisher = AsyncMock(spec=EventPublisher)
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        await proc.process_pending()  # type: ignore[attr-defined]

        publisher.publish.assert_awaited_once()
        outbox_repo.mark_failed.assert_not_awaited()


# ── Return value ──────────────────────────────────────────────────────────────


class TestReturnValue:
    @pytest.mark.asyncio
    async def test_empty_batch_returns_zero(self) -> None:
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = []
        proc = make_processor(outbox_repo=outbox_repo)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 0

    @pytest.mark.asyncio
    async def test_mixed_batch_counts_only_successes(self) -> None:
        """2 succeed, 1 fails, 1 at max-retry → return 2."""
        ok1 = make_event(event_id="ok1", retry_count=0)
        ok2 = make_event(event_id="ok2", retry_count=0)
        fail = make_event(event_id="fail", retry_count=0)
        maxretry = make_event(event_id="maxretry", retry_count=5)

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.find_pending.return_value = [ok1, ok2, fail, maxretry]
        publisher = AsyncMock(spec=EventPublisher)
        publisher.publish.side_effect = [
            None,  # ok1 succeeds
            None,  # ok2 succeeds
            ExternalServiceError(message="fail", user_message="err"),  # fail
            # maxretry never reaches publish
        ]
        proc = make_processor(outbox_repo=outbox_repo, publisher=publisher)

        count = await proc.process_pending()  # type: ignore[attr-defined]

        assert count == 2
