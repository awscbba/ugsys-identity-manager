"""EventBridge publisher — infrastructure adapter for domain events."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import boto3
import structlog

from src.domain.repositories.event_publisher import EventPublisher as EventPublisherABC
from src.presentation.middleware.correlation_id import correlation_id_var

logger = structlog.get_logger()

SOURCE = "ugsys.identity-manager"
EVENT_VERSION = "1.0"


class EventBridgePublisher(EventPublisherABC):
    """Publishes domain events to EventBridge using ugsys-event-lib envelope format."""

    def __init__(self, bus_name: str, region: str = "us-east-1") -> None:
        self._bus_name = bus_name
        self._client = boto3.client("events", region_name=region)

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
            self._client.put_events(
                Entries=[
                    {
                        "EventBusName": self._bus_name,
                        "Source": SOURCE,
                        "DetailType": detail_type,
                        "Detail": json.dumps(envelope),
                    }
                ]
            )
            logger.info("event.published", detail_type=detail_type, event_id=event_id)
        except Exception as e:
            logger.error("event.publish_failed", detail_type=detail_type, error=str(e))
