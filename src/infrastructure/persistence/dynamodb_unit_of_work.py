"""DynamoDB Unit of Work — adapter implementing UnitOfWork port.

Wraps DynamoDB TransactWriteItems to execute multiple repository operations
atomically: all succeed or all fail.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
import structlog
from botocore.exceptions import ClientError

from src.domain.exceptions import RepositoryError
from src.domain.repositories.unit_of_work import TransactionalOperation, UnitOfWork

logger = structlog.get_logger()

_DYNAMODB_TRANSACTION_LIMIT = 100


class DynamoDBUnitOfWork(UnitOfWork):
    """Executes a list of TransactionalOperations as a single DynamoDB TransactWriteItems call."""

    def __init__(
        self,
        region: str = "us-east-1",
        session: aioboto3.Session | None = None,
        client: object = None,  # pre-built client for unit tests
    ) -> None:
        self._region = region
        self._session = session or aioboto3.Session()
        self._test_client = client

    @asynccontextmanager
    async def _get_client(self) -> AsyncGenerator[Any]:
        """Yield a DynamoDB client — pre-built (tests) or session-managed (prod)."""
        test_client = getattr(self, "_test_client", None) or getattr(self, "_client", None)
        if test_client is not None:
            yield test_client
        else:
            async with self._session.client("dynamodb", region_name=self._region) as client:
                yield client

    async def execute(self, operations: list[TransactionalOperation]) -> None:
        """Execute all operations atomically.

        - Empty list: returns immediately, no DynamoDB call.
        - > 100 operations: raises RepositoryError before any DynamoDB call.
        - 1-100 operations: calls transact_write_items exactly once.
        """
        if not operations:
            return

        if len(operations) > _DYNAMODB_TRANSACTION_LIMIT:
            raise RepositoryError(
                message=(
                    f"Transaction exceeds DynamoDB limit: {len(operations)} operations "
                    f"(max {_DYNAMODB_TRANSACTION_LIMIT})"
                ),
                user_message="An unexpected error occurred",
                error_code="REPOSITORY_ERROR",
            )

        transact_items = [{op.operation_type: op.params} for op in operations]

        try:
            async with self._get_client() as client:
                await client.transact_write_items(TransactItems=transact_items)
            logger.info("unit_of_work.committed", operation_count=len(operations))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "TransactionCanceledException":
                reasons = e.response.get("CancellationReasons", [])
                logger.error(
                    "unit_of_work.transaction_cancelled",
                    operation_count=len(operations),
                    cancellation_reasons=reasons,
                    error=str(e),
                )
            else:
                logger.error(
                    "unit_of_work.transaction_failed",
                    error_code=code,
                    operation_count=len(operations),
                    error=str(e),
                )
            raise RepositoryError(
                message=f"DynamoDB transaction failed ({code}): {e}",
                user_message="An unexpected error occurred",
                error_code="REPOSITORY_ERROR",
            ) from e
