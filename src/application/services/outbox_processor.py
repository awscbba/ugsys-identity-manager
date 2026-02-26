"""OutboxProcessor application service.

Reads pending outbox events and delivers them to EventBridge.
Handles retry logic and max-retry failure marking.
"""

import json
import time

import structlog

from src.domain.repositories.event_publisher import EventPublisher
from src.domain.repositories.outbox_repository import OutboxRepository

logger = structlog.get_logger()

_MAX_RETRIES = 5


class OutboxProcessor:
    def __init__(
        self,
        outbox_repo: OutboxRepository,
        publisher: EventPublisher,
    ) -> None:
        self._outbox_repo = outbox_repo
        self._publisher = publisher

    async def process_pending(self, batch_size: int = 25) -> int:
        """Fetch pending outbox events and deliver them to EventBridge.

        Returns the count of successfully published events.
        """
        start = time.perf_counter()
        events = await self._outbox_repo.find_pending(limit=batch_size)
        published = 0

        for event in events:
            if event.retry_count >= _MAX_RETRIES:
                await self._outbox_repo.mark_failed(event.id)
                logger.error(
                    "outbox.max_retries_exceeded",
                    event_id=event.id,
                    event_type=event.event_type,
                    retry_count=event.retry_count,
                )
                continue

            try:
                payload = json.loads(event.payload)
                await self._publisher.publish(event.event_type, payload)
                await self._outbox_repo.mark_published(event.id)
                published += 1
            except Exception as e:
                logger.error(
                    "outbox.delivery_failed",
                    event_id=event.id,
                    event_type=event.event_type,
                    error=str(e),
                )
                await self._outbox_repo.increment_retry(event.id)

        logger.info(
            "outbox.process_pending.completed",
            published=published,
            total=len(events),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return published
