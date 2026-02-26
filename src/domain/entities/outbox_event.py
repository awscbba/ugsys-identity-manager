"""OutboxEvent domain entity.

Represents a pending domain event stored in the outbox table.
Zero imports from infrastructure, application, or presentation layers.
"""

from dataclasses import dataclass


@dataclass
class OutboxEvent:
    """A domain event pending delivery via the outbox pattern."""

    id: str  # ULID
    aggregate_type: str  # e.g. "User"
    aggregate_id: str  # entity UUID/ULID
    event_type: str  # e.g. "identity.user.registered"
    payload: str  # JSON string
    created_at: str  # ISO 8601 UTC
    status: str  # "pending" | "published" | "failed"
    retry_count: int = 0
    published_at: str | None = None
