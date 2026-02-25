"""Integration tests for DynamoDBUserRepository against a moto-backed DynamoDB."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import boto3

from src.domain.entities.user import User, UserRole, UserStatus
from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository


def _make_user(**kwargs: object) -> User:
    """Return a minimal valid User, overridable via kwargs."""
    defaults: dict[str, object] = {
        "email": f"user-{uuid4()}@test.com",
        "hashed_password": "hashed_pw",
        "full_name": "Test User",
        "status": UserStatus.ACTIVE,
        "roles": [UserRole.MEMBER],
    }
    defaults.update(kwargs)
    return User(**defaults)  # type: ignore[arg-type]


async def test_save_and_find_by_id(user_repo: DynamoDBUserRepository) -> None:
    # Arrange
    user = _make_user(email="alice@test.com", full_name="Alice Smith")

    # Act
    await user_repo.save(user)
    found = await user_repo.find_by_id(user.id)

    # Assert
    assert found is not None
    assert found.email == "alice@test.com"
    assert found.full_name == "Alice Smith"
    assert found.status == UserStatus.ACTIVE


async def test_find_by_email(user_repo: DynamoDBUserRepository) -> None:
    # Arrange
    user = _make_user(email="bob@test.com")
    await user_repo.save(user)

    # Act
    found = await user_repo.find_by_email("bob@test.com")

    # Assert
    assert found is not None
    assert found.id == user.id


async def test_find_by_email_not_found(user_repo: DynamoDBUserRepository) -> None:
    # Act
    found = await user_repo.find_by_email("nobody@test.com")

    # Assert
    assert found is None


async def test_find_by_id_not_found(user_repo: DynamoDBUserRepository) -> None:
    # Act
    found = await user_repo.find_by_id(uuid4())

    # Assert
    assert found is None


async def test_round_trip_all_security_fields(user_repo: DynamoDBUserRepository) -> None:
    # Arrange
    user = _make_user(
        email="secure@test.com",
        failed_login_attempts=3,
        require_password_change=True,
        email_verified=True,
        email_verification_token="tok123",
        is_admin=True,
    )

    # Act
    await user_repo.save(user)
    found = await user_repo.find_by_id(user.id)

    # Assert
    assert found is not None
    assert found.failed_login_attempts == 3
    assert found.require_password_change is True
    assert found.email_verified is True
    assert found.email_verification_token == "tok123"
    assert found.is_admin is True


async def test_legacy_item_defaults(
    user_repo: DynamoDBUserRepository,
    users_table_name: str,
) -> None:
    # Arrange — write a minimal legacy item directly via boto3 (no security fields)
    user_id = uuid4()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(users_table_name)
    table.put_item(
        Item={
            "pk": f"USER#{user_id}",
            "sk": "PROFILE",
            "id": str(user_id),
            "email": "legacy@test.com",
            "hashed_password": "hashed",
            "full_name": "Legacy User",
            "status": "active",
            "roles": ["member"],
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )

    # Act
    found = await user_repo.find_by_id(user_id)

    # Assert — backward-compatible defaults applied
    assert found is not None
    assert found.failed_login_attempts == 0
    assert found.email_verified is True  # legacy active user assumed verified
    assert found.require_password_change is False
    assert found.is_admin is False


async def test_update_persists_changes(user_repo: DynamoDBUserRepository) -> None:
    # Arrange
    user = _make_user(email="charlie@test.com", full_name="Charlie Old")
    await user_repo.save(user)

    # Act
    user.full_name = "Charlie New"
    await user_repo.update(user)
    found = await user_repo.find_by_id(user.id)

    # Assert
    assert found is not None
    assert found.full_name == "Charlie New"


async def test_list_paginated_returns_page_and_total(user_repo: DynamoDBUserRepository) -> None:
    # Arrange — save 5 distinct users
    for i in range(5):
        await user_repo.save(_make_user(email=f"page-user-{i}@test.com"))

    # Act
    users, total = await user_repo.list_paginated(page=1, page_size=2)

    # Assert
    assert total == 5
    assert len(users) == 2


async def test_list_paginated_status_filter(user_repo: DynamoDBUserRepository) -> None:
    # Arrange — 3 active + 2 inactive
    for i in range(3):
        await user_repo.save(_make_user(email=f"active-{i}@test.com", status=UserStatus.ACTIVE))
    for i in range(2):
        await user_repo.save(_make_user(email=f"inactive-{i}@test.com", status=UserStatus.INACTIVE))

    # Act
    users, total = await user_repo.list_paginated(page=1, page_size=10, status_filter="active")

    # Assert
    assert total == 3
    assert all(u.status == UserStatus.ACTIVE for u in users)


async def test_find_by_verification_token(user_repo: DynamoDBUserRepository) -> None:
    # Arrange
    user = _make_user(
        email="verify@test.com",
        email_verification_token="abc-token",
        status=UserStatus.PENDING_VERIFICATION,
    )
    await user_repo.save(user)

    # Act
    found = await user_repo.find_by_verification_token("abc-token")

    # Assert
    assert found is not None
    assert found.id == user.id
    assert found.email == "verify@test.com"


async def test_find_by_verification_token_not_found(user_repo: DynamoDBUserRepository) -> None:
    # Act
    found = await user_repo.find_by_verification_token("unknown")

    # Assert
    assert found is None
