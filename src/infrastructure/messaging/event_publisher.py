"""EventBridge publisher — infrastructure adapter for domain events.

Uses aioboto3 for non-blocking async I/O. A short-lived client is opened
per publish() call via an async context manager, consistent with the DynamoDB
client pattern in main.py.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aioboto3
import structlog

from src.domain.exceptions import ExternalServiceError
from src.domain.repositories.event_publisher import EventPublisher as EventPublisherABC
from src.presentation.middleware.correlation_id import correlation_id_var

logger = structlog.get_logger()

SOURCE = "ugsys.identity-manager"
EVENT_VERSION = "1.0"


class EventBridgePublisher(EventPublisherABC):
    """Publishes domain events to EventBridge using ugsys-event-lib envelope format.

    Constructor changes from the old implementation:
    - Removed: self._client = boto3.client(...)  (synchronous, created at startup)
    - Added:   self._session: aioboto3.Session   (async, client opened per call)
    """

    def __init__(
        self,
        bus_name: str,
        region: str = "us-east-1",
        session: aioboto3.Session | None = None,
    ) -> None:
        self._bus_name = bus_name
        self._region = region
        self._session = session or aioboto3.Session()

    async def publish(self, detail_type: str, payload: dict[str, Any]) -> None:
        event_id = str(uuid4())
        correlation_id = correlation_id_var.get("")
        envelope = {
            "event_id": event_id,
            "event_version": EVENT_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": correlation_id,
            "payload": payload,
        }
        try:
            async with self._session.client("events", region_name=self._region) as client:
                response = await client.put_events(
                    Entries=[
                        {
                            "EventBusName": self._bus_name,
                            "Source": SOURCE,
                            "DetailType": detail_type,
                            "Detail": json.dumps(envelope),
                        }
                    ]
                )
            if response["FailedEntryCount"] > 0:
                failed = response.get("Entries", [])
                raise ExternalServiceError(
                    message=(
                        f"EventBridge put_events partial failure for {detail_type!r}: "
                        f"FailedEntryCount={response['FailedEntryCount']}, entries={failed}"
                    ),
                    user_message="An unexpected error occurred",
                    error_code="EXTERNAL_SERVICE_ERROR",
                )
            logger.info("event.published", detail_type=detail_type, event_id=event_id)
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error(
                "event.publish_failed",
                detail_type=detail_type,
                event_id=event_id,
                error=str(e),
            )
            raise ExternalServiceError(
                message=f"EventBridge publish failed for {detail_type!r}: {e}",
                user_message="An unexpected error occurred",
                error_code="EXTERNAL_SERVICE_ERROR",
            ) from e
