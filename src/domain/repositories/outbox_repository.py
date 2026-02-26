"""OutboxRepository domain port.

Abstract base class for reading and writing OutboxEvent records.
Zero imports from infrastructure, application, or presentation layers.
"""

from abc import ABC, abstractmethod

from src.domain.entities.outbox_event import OutboxEvent
from src.domain.repositories.unit_of_work import TransactionalOperation


class OutboxRepository(ABC):
    """Port for persisting and querying outbox events."""

    @abstractmethod
    async def save(self, event: OutboxEvent) -> OutboxEvent:
        """Persist a new outbox event with status='pending'."""
        ...

    @abstractmethod
    async def find_pending(self, limit: int) -> list[OutboxEvent]:
        """Return up to `limit` events with status='pending', ordered by created_at asc."""
        ...

    @abstractmethod
    async def mark_published(self, event_id: str) -> None:
        """Set status='published' and published_at to current UTC timestamp."""
        ...

    @abstractmethod
    async def increment_retry(self, event_id: str) -> None:
        """Atomically increment retry_count by 1."""
        ...

    @abstractmethod
    async def mark_failed(self, event_id: str) -> None:
        """Set status='failed'."""
        ...

    @abstractmethod
    def save_operation(self, event: OutboxEvent) -> TransactionalOperation:
        """Return a TransactionalOperation for use in UnitOfWork.execute() — no I/O."""
        ...
