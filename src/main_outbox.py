"""Outbox Lambda entry point.

Standalone handler — no FastAPI, no Mangum.
Triggered by EventBridge Scheduler every minute to drain the outbox table.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aioboto3
import structlog

from src.application.services.outbox_processor import OutboxProcessor
from src.config import settings
from src.infrastructure.logging import configure_logging
from src.infrastructure.messaging.event_publisher import EventBridgePublisher
from src.infrastructure.persistence.dynamodb_outbox_repository import DynamoDBOutboxRepository

configure_logging(settings.service_name, settings.log_level)
logger = structlog.get_logger()


async def _build_processor() -> OutboxProcessor:
    """Wire infrastructure adapters. Kept as a separate async function so tests can patch it."""
    session = aioboto3.Session()
    publisher = EventBridgePublisher(
        bus_name=settings.event_bus_name,
        region=settings.aws_region,
        session=session,
    )
    # DynamoDBOutboxRepository needs a pre-built client; we open it here and
    # keep it alive for the duration of process_pending().
    async with session.client("dynamodb", region_name=settings.aws_region) as dynamodb_client:
        outbox_repo = DynamoDBOutboxRepository(
            table_name=settings.outbox_table,
            client=dynamodb_client,
        )
        return OutboxProcessor(outbox_repo=outbox_repo, publisher=publisher)


async def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Async Lambda handler — drains pending outbox events."""
    logger.info("outbox_handler.started", service=settings.service_name)
    processor = await _build_processor()
    published = await processor.process_pending()
    logger.info("outbox_handler.completed", published=published)
    return {"status": "ok", "published": published}


def sync_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Synchronous Lambda entry point required by the Lambda runtime."""
    return asyncio.run(handler(event, context))
