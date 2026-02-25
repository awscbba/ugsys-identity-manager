"""DynamoDB token blacklist repository — adapter implementing TokenBlacklistRepository port."""

import boto3
import structlog

from src.domain.repositories.token_blacklist_repository import TokenBlacklistRepository

logger = structlog.get_logger()


class DynamoDBTokenBlacklistRepository(TokenBlacklistRepository):
    def __init__(self, table_name: str, region: str = "us-east-1") -> None:
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    async def add(self, jti: str, ttl_epoch: int) -> None:
        self._table.put_item(Item={"jti": jti, "ttl": ttl_epoch})
        logger.info("token_blacklist.added", jti=jti)

    async def is_blacklisted(self, jti: str) -> bool:
        resp = self._table.get_item(Key={"jti": jti})
        exists = "Item" in resp
        if exists:
            logger.info("token_blacklist.hit", jti=jti)
        return exists
