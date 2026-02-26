"""Bug condition exploration tests — DynamoDB ClientError wrapping in TokenBlacklist (Gap 2).

**Validates: Requirements 1.7**
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from src.domain.exceptions import RepositoryError
from src.infrastructure.persistence.dynamodb_token_blacklist import (
    DynamoDBTokenBlacklistRepository,
)


def _make_client_error(code: str = "InternalServerError") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": f"Simulated {code}"}},
        operation_name="TestOperation",
    )


def _make_repo(table_mock: AsyncMock) -> DynamoDBTokenBlacklistRepository:
    session = MagicMock()

    @asynccontextmanager
    async def _fake_resource(*args: object, **kwargs: object):  # type: ignore[misc]
        resource = AsyncMock()
        resource.Table = AsyncMock(return_value=table_mock)
        yield resource

    session.resource = _fake_resource
    return DynamoDBTokenBlacklistRepository(
        table_name="test-blacklist", region="us-east-1", session=session
    )


@pytest.mark.asyncio
async def test_add_client_error_raises_repository_error() -> None:
    """Requirement 2.8: ClientError from add() must be caught and re-raised as RepositoryError."""
    table = AsyncMock()
    table.put_item.side_effect = _make_client_error()
    repo = _make_repo(table)

    with pytest.raises(RepositoryError):
        await repo.add(jti="some-jti-value", ttl_epoch=9999999999)


@pytest.mark.asyncio
async def test_is_blacklisted_client_error_raises_repository_error() -> None:
    """Requirement 2.8: ClientError from is_blacklisted() must be caught and
    re-raised as RepositoryError."""
    table = AsyncMock()
    table.get_item.side_effect = _make_client_error()
    repo = _make_repo(table)

    with pytest.raises(RepositoryError):
        await repo.is_blacklisted(jti="some-jti-value")
