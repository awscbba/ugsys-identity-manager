"""EventBridge publisher — infrastructure adapter for domain events."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import boto3
import structlog

logger = structlog.get_logger()


class EventPublisher:
    def __init__(self, bus_name: str, region: str = "us-east-1") -> None:
        self._bus_name = bus_name
        self._client = boto3.client("events", region_name=region)

    def publish(self, source: str, detail_type: str, detail: dict) -> None:  # type: ignore[type-arg]
        event_id = str(uuid4())
        payload = {
            "event_id": event_id,
            "timestamp": datetime.now(UTC).isoformat(),
            **detail,
        }
        try:
            self._client.put_events(
                Entries=[
                    {
                        "EventBusName": self._bus_name,
                        "Source": source,
                        "DetailType": detail_type,
                        "Detail": json.dumps(payload),
                    }
                ]
            )
            logger.info("event.published", detail_type=detail_type, event_id=event_id)
        except Exception as e:
            # Non-fatal — log and continue; events are best-effort at this stage
            logger.error("event.publish_failed", detail_type=detail_type, error=str(e))
