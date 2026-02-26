"""DynamoDB outbox repository — adapter implementing OutboxRepository port.

Uses aioboto3 for non-blocking async I/O. A short-lived client is opened
per operation via async context manager, consistent with the session-based
pattern used across all adapters.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import aioboto3
import structlog
from botocore.exceptions import ClientError

from src.domain.entities.outbox_event import OutboxEvent
from src.domain.exceptions import RepositoryError
from src.domain.repositories.outbox_repository import OutboxRepository
from src.domain.repositories.unit_of_work import TransactionalOperation

logger = structlog.get_logger()


class DynamoDBOutboxRepository(OutboxRepository):
    """DynamoDB implementation of the OutboxRepository port.

    Opens a short-lived client per operation via async context manager,
    consistent with the session-based pattern used across all adapters.
    Accepts a pre-built client for unit tests.
    """

    def __init__(
        self,
        table_name: str,
        region: str = "us-east-1",
        session: aioboto3.Session | None = None,
        client: object = None,  # pre-built client for unit tests
    ) -> None:
        self._table_name = table_name
        self._region = region
        self._session = session or aioboto3.Session()
        self._test_client = client  # if set, bypasses session (unit tests only)

    @asynccontextmanager
    async def _get_client(self) -> AsyncGenerator[Any]:
        """Yield a DynamoDB client — pre-built (tests) or session-managed (prod)."""
        test_client = getattr(self, "_test_client", None) or getattr(self, "_client", None)
        if test_client is not None:
            yield test_client
        else:
            async with self._session.client("dynamodb", region_name=self._region) as client:
                yield client

    # ── Public interface ──────────────────────────────────────────────────────

    async def save(self, event: OutboxEvent) -> OutboxEvent:
        """Persist a new outbox event, forcing status='pending' and retry_count=0."""
        # Build item with forced pending state regardless of input values
        item = self._to_item(event)
        item["status"] = {"S": "pending"}
        item["retry_count"] = {"N": "0"}
        try:
            async with self._get_client() as client:
                await client.put_item(
                    TableName=self._table_name,
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK)",
                )
            logger.info("outbox.saved", event_id=event.id, event_type=event.event_type)
            return event
        except ClientError as e:
            self._raise_repository_error("save", e)
            raise  # unreachable — satisfies mypy

    async def find_pending(self, limit: int) -> list[OutboxEvent]:
        """Query StatusIndex GSI for pending events, ordered by created_at ascending."""
        try:
            async with self._get_client() as client:
                response = await client.query(
                    TableName=self._table_name,
                    IndexName="StatusIndex",
                    KeyConditionExpression="#s = :status",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":status": {"S": "pending"}},
                    ScanIndexForward=True,
                    Limit=limit,
                )
            items = response.get("Items", [])
            return [self._from_item(item) for item in items]
        except ClientError as e:
            self._raise_repository_error("find_pending", e)
            raise  # unreachable

    async def mark_published(self, event_id: str) -> None:
        """Set status='published' and published_at to current UTC ISO 8601 timestamp."""
        published_at = datetime.now(UTC).isoformat()
        try:
            async with self._get_client() as client:
                await client.update_item(
                    TableName=self._table_name,
                    Key={
                        "PK": {"S": f"OUTBOX#{event_id}"},
                        "SK": {"S": "EVENT"},
                    },
                    UpdateExpression="SET #s = :status, published_at = :published_at",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":status": {"S": "published"},
                        ":published_at": {"S": published_at},
                    },
                )
            logger.info("outbox.published", event_id=event_id)
        except ClientError as e:
            self._raise_repository_error("mark_published", e)
            raise  # unreachable

    async def increment_retry(self, event_id: str) -> None:
        """Atomically increment retry_count by 1 using DynamoDB ADD expression."""
        try:
            async with self._get_client() as client:
                await client.update_item(
                    TableName=self._table_name,
                    Key={
                        "PK": {"S": f"OUTBOX#{event_id}"},
                        "SK": {"S": "EVENT"},
                    },
                    UpdateExpression="ADD retry_count :one",
                    ExpressionAttributeValues={":one": {"N": "1"}},
                )
            logger.info("outbox.retry_incremented", event_id=event_id)
        except ClientError as e:
            self._raise_repository_error("increment_retry", e)
            raise  # unreachable

    async def mark_failed(self, event_id: str) -> None:
        """Set status='failed'."""
        try:
            async with self._get_client() as client:
                await client.update_item(
                    TableName=self._table_name,
                    Key={
                        "PK": {"S": f"OUTBOX#{event_id}"},
                        "SK": {"S": "EVENT"},
                    },
                    UpdateExpression="SET #s = :status",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":status": {"S": "failed"}},
                )
            logger.info("outbox.failed", event_id=event_id)
        except ClientError as e:
            self._raise_repository_error("mark_failed", e)
            raise  # unreachable

    def save_operation(self, event: OutboxEvent) -> TransactionalOperation:
        """Return a TransactionalOperation for use in UnitOfWork.execute() — no I/O.

        The item always has status='pending' and retry_count=0 so that the
        transactional write enforces the same invariant as save().
        """
        item = self._to_item(event)
        item["status"] = {"S": "pending"}
        item["retry_count"] = {"N": "0"}
        return TransactionalOperation(
            operation_type="Put",
            params={
                "TableName": self._table_name,
                "Item": item,
                "ConditionExpression": "attribute_not_exists(PK)",
            },
        )

    # ── Serialization ─────────────────────────────────────────────────────────

    def _to_item(self, event: OutboxEvent) -> dict[str, Any]:
        """Convert OutboxEvent to DynamoDB low-level AttributeValue dict."""
        item: dict[str, Any] = {
            "PK": {"S": f"OUTBOX#{event.id}"},
            "SK": {"S": "EVENT"},
            "id": {"S": event.id},
            "aggregate_type": {"S": event.aggregate_type},
            "aggregate_id": {"S": event.aggregate_id},
            "event_type": {"S": event.event_type},
            "payload": {"S": event.payload},
            "created_at": {"S": event.created_at},
            "status": {"S": event.status},
            "retry_count": {"N": str(event.retry_count)},
        }
        # Only write published_at when present — never store None
        if event.published_at is not None:
            item["published_at"] = {"S": event.published_at}
        return item

    def _from_item(self, item: dict[str, Any]) -> OutboxEvent:
        """Convert DynamoDB low-level item to OutboxEvent. Uses .get() with safe defaults."""
        return OutboxEvent(
            id=item["id"]["S"],
            aggregate_type=item["aggregate_type"]["S"],
            aggregate_id=item["aggregate_id"]["S"],
            event_type=item["event_type"]["S"],
            payload=item["payload"]["S"],
            created_at=item["created_at"]["S"],
            status=item.get("status", {}).get("S", "pending"),
            retry_count=int(item.get("retry_count", {}).get("N", "0")),
            published_at=item.get("published_at", {}).get("S"),
        )

    # ── Error handling ────────────────────────────────────────────────────────

    def _raise_repository_error(self, operation: str, e: ClientError) -> None:
        """Log full ClientError internally; raise RepositoryError with safe user_message."""
        logger.error(
            "dynamodb.outbox.error",
            operation=operation,
            table=self._table_name,
            error_code=e.response["Error"]["Code"],
            error=str(e),
        )
        raise RepositoryError(
            message=f"DynamoDB outbox {operation} failed on {self._table_name}: {e}",
            user_message="An unexpected error occurred",
            error_code="REPOSITORY_ERROR",
        )
