"""Event publisher port (interface)."""

from abc import ABC, abstractmethod
from typing import Any


class EventPublisher(ABC):
    """Port for publishing domain events to the event bus."""

    @abstractmethod
    async def publish(self, detail_type: str, payload: dict[str, Any]) -> None:
        """Publish a domain event. Source is set by the infrastructure adapter."""
        ...
