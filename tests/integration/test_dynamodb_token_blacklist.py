"""Integration tests for DynamoDBTokenBlacklistRepository against a moto-backed DynamoDB."""

from __future__ import annotations

from src.infrastructure.persistence.dynamodb_token_blacklist import (
    DynamoDBTokenBlacklistRepository,
)

# Far-future epoch so moto never treats the item as TTL-expired during tests
_FAR_FUTURE_TTL = 9_999_999_999


async def test_add_and_is_blacklisted(blacklist_repo: DynamoDBTokenBlacklistRepository) -> None:
    # Arrange
    jti = "test-jti-1"

    # Act
    await blacklist_repo.add(jti, _FAR_FUTURE_TTL)

    # Assert
    assert await blacklist_repo.is_blacklisted(jti) is True


async def test_is_blacklisted_unknown_jti(
    blacklist_repo: DynamoDBTokenBlacklistRepository,
) -> None:
    # Act + Assert
    assert await blacklist_repo.is_blacklisted("unknown-jti") is False


async def test_add_idempotent(blacklist_repo: DynamoDBTokenBlacklistRepository) -> None:
    # Arrange
    jti = "idempotent-jti"

    # Act — add the same jti twice; must not raise
    await blacklist_repo.add(jti, _FAR_FUTURE_TTL)
    await blacklist_repo.add(jti, _FAR_FUTURE_TTL)

    # Assert — still blacklisted
    assert await blacklist_repo.is_blacklisted(jti) is True


async def test_multiple_jtis_independent(
    blacklist_repo: DynamoDBTokenBlacklistRepository,
) -> None:
    # Arrange
    jti_a = "jti-a"
    jti_b = "jti-b"

    # Act
    await blacklist_repo.add(jti_a, _FAR_FUTURE_TTL)

    # Assert — jti-b not blacklisted, jti-a is
    assert await blacklist_repo.is_blacklisted(jti_b) is False
    assert await blacklist_repo.is_blacklisted(jti_a) is True
