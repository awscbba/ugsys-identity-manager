"""DynamoDB token blacklist repository — adapter implementing TokenBlacklistRepository port."""

import aioboto3
import structlog
from botocore.exceptions import ClientError

from src.domain.exceptions import RepositoryError
from src.domain.repositories.token_blacklist_repository import TokenBlacklistRepository

logger = structlog.get_logger()


class DynamoDBTokenBlacklistRepository(TokenBlacklistRepository):
    def __init__(
        self,
        table_name: str,
        region: str = "us-east-1",
        session: aioboto3.Session | None = None,
    ) -> None:
        self._table_name = table_name
        self._region = region
        self._session = session or aioboto3.Session()

    def _raise_repository_error(self, operation: str, e: ClientError) -> None:
        logger.error(
            "dynamodb.error",
            operation=operation,
            table=self._table_name,
            error_code=e.response["Error"]["Code"],
            error=str(e),
        )
        raise RepositoryError(
            message=f"DynamoDB {operation} failed: {e}",
            user_message="An unexpected error occurred",
            error_code="REPOSITORY_ERROR",
        )

    async def add(self, jti: str, ttl_epoch: int) -> None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                await table.put_item(Item={"jti": jti, "ttl": ttl_epoch})
            logger.info("token_blacklist.added", jti=jti)
        except ClientError as e:
            self._raise_repository_error("add", e)

    async def is_blacklisted(self, jti: str) -> bool:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                resp = await table.get_item(Key={"jti": jti})
            exists = "Item" in resp
            if exists:
                logger.info("token_blacklist.hit", jti=jti)
            return exists
        except ClientError as e:
            self._raise_repository_error("is_blacklisted", e)
            raise
