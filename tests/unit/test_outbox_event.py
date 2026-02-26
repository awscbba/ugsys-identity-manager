"""Unit tests for OutboxEvent dataclass.

TDD: RED phase — these tests will fail until the implementation exists.
"""

import dataclasses
from dataclasses import fields


class TestOutboxEventDefaults:
    """Tests for OutboxEvent field defaults."""

    def test_retry_count_defaults_to_zero(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JXXX",
            aggregate_type="User",
            aggregate_id="user-123",
            event_type="identity.user.registered",
            payload='{"user_id": "user-123"}',
            created_at="2025-01-01T00:00:00+00:00",
            status="pending",
        )
        assert event.retry_count == 0

    def test_published_at_defaults_to_none(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JXXX",
            aggregate_type="User",
            aggregate_id="user-123",
            event_type="identity.user.registered",
            payload='{"user_id": "user-123"}',
            created_at="2025-01-01T00:00:00+00:00",
            status="pending",
        )
        assert event.published_at is None

    def test_status_field_accepts_pending(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JXXX",
            aggregate_type="User",
            aggregate_id="user-123",
            event_type="identity.user.registered",
            payload="{}",
            created_at="2025-01-01T00:00:00+00:00",
            status="pending",
        )
        assert event.status == "pending"

    def test_status_field_accepts_published(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JXXX",
            aggregate_type="User",
            aggregate_id="user-123",
            event_type="identity.user.registered",
            payload="{}",
            created_at="2025-01-01T00:00:00+00:00",
            status="published",
        )
        assert event.status == "published"

    def test_status_field_accepts_failed(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JXXX",
            aggregate_type="User",
            aggregate_id="user-123",
            event_type="identity.user.registered",
            payload="{}",
            created_at="2025-01-01T00:00:00+00:00",
            status="failed",
        )
        assert event.status == "failed"


class TestOutboxEventFields:
    """Tests for OutboxEvent field presence and types."""

    def test_outbox_event_is_dataclass(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        assert dataclasses.is_dataclass(OutboxEvent)

    def test_outbox_event_has_all_required_fields(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        field_names = {f.name for f in fields(OutboxEvent)}
        required = {
            "id",
            "aggregate_type",
            "aggregate_id",
            "event_type",
            "payload",
            "created_at",
            "status",
            "retry_count",
            "published_at",
        }
        assert required.issubset(field_names)

    def test_outbox_event_all_fields_set_correctly(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent

        event = OutboxEvent(
            id="01JYYY",
            aggregate_type="User",
            aggregate_id="abc-123",
            event_type="identity.user.deactivated",
            payload='{"user_id": "abc-123"}',
            created_at="2025-06-01T12:00:00+00:00",
            status="pending",
            retry_count=2,
            published_at="2025-06-01T12:05:00+00:00",
        )
        assert event.id == "01JYYY"
        assert event.aggregate_type == "User"
        assert event.aggregate_id == "abc-123"
        assert event.event_type == "identity.user.deactivated"
        assert event.payload == '{"user_id": "abc-123"}'
        assert event.created_at == "2025-06-01T12:00:00+00:00"
        assert event.status == "pending"
        assert event.retry_count == 2
        assert event.published_at == "2025-06-01T12:05:00+00:00"


class TestOutboxEventPurity:
    """Tests that OutboxEvent has zero external layer imports."""

    def test_outbox_event_has_no_infra_imports(self) -> None:
        """Domain entity must have zero imports from infra/application/presentation."""
        import ast
        import pathlib

        import pytest

        source_path = pathlib.Path("src/domain/entities/outbox_event.py")
        if not source_path.exists():
            pytest.skip("Implementation not yet created")

        source = source_path.read_text()
        tree = ast.parse(source)

        forbidden_prefixes = (
            "src.infrastructure",
            "src.application",
            "src.presentation",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    assert not node.module.startswith(prefix), (
                        f"Domain entity must not import from {prefix}, found: from {node.module}"
                    )
