"""Bug condition exploration tests — DynamoDB ClientError wrapping in UserRepository (Gap 2).

**Validates: Requirements 1.6, 1.8, 1.9**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import NotFoundError, RepositoryError
from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository


def _make_client_error(code: str) -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": f"Simulated {code}"}},
        operation_name="TestOperation",
    )


def _make_repo(table_mock: AsyncMock) -> DynamoDBUserRepository:
    """Return a repository instance whose session yields the given mock table."""
    session = MagicMock()

    @asynccontextmanager
    async def _fake_resource(*args: object, **kwargs: object):  # type: ignore[misc]
        resource = AsyncMock()
        resource.Table = AsyncMock(return_value=table_mock)
        yield resource

    session.resource = _fake_resource
    return DynamoDBUserRepository(table_name="test-table", region="us-east-1", session=session)


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=UserStatus.ACTIVE,
        roles=[UserRole.MEMBER],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ── Bug 1.6: ClientError leaks from find_by_id ───────────────────────────────


@pytest.mark.asyncio
async def test_find_by_id_client_error_raises_repository_error() -> None:
    """Requirement 2.7: ClientError from find_by_id must be caught and
    re-raised as RepositoryError."""
    table = AsyncMock()
    table.get_item.side_effect = _make_client_error("InternalServerError")
    repo = _make_repo(table)

    with pytest.raises(RepositoryError):
        await repo.find_by_id(uuid4())


# ── Bug 1.8: ConditionalCheckFailedException on save leaks ──────────────────


@pytest.mark.asyncio
async def test_save_conditional_check_failed_raises_repository_error() -> None:
    """Requirement 2.9: ConditionalCheckFailedException on save() must raise RepositoryError."""
    table = AsyncMock()
    table.put_item.side_effect = _make_client_error("ConditionalCheckFailedException")
    repo = _make_repo(table)

    with pytest.raises(RepositoryError):
        await repo.save(_make_user())


# ── Bug 1.9: ConditionalCheckFailedException on update leaks ─────────────────


@pytest.mark.asyncio
async def test_update_conditional_check_failed_raises_not_found_error() -> None:
    """Requirement 2.10: ConditionalCheckFailedException on update() must raise NotFoundError."""
    table = AsyncMock()
    table.put_item.side_effect = _make_client_error("ConditionalCheckFailedException")
    repo = _make_repo(table)

    with pytest.raises(NotFoundError):
        await repo.update(_make_user())


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_preservation_save_returns_same_user_entity() -> None:
    """Preservation 3.8: Successful save() must return the same User entity passed in."""
    table = AsyncMock()
    table.put_item.return_value = {}
    repo = _make_repo(table)

    user = _make_user()
    result = await repo.save(user)

    assert result is user, "save() must return the same User entity that was passed in"


@pytest.mark.asyncio
async def test_preservation_find_by_id_returns_correct_user_entity() -> None:
    """Preservation 3.8: Successful find_by_id() must return the correct User entity."""
    table = AsyncMock()
    user_id = uuid4()
    now_iso = datetime.now(UTC).isoformat()

    table.get_item.return_value = {
        "Item": {
            "pk": f"USER#{user_id}",
            "sk": "PROFILE",
            "id": str(user_id),
            "email": "preserve@example.com",
            "hashed_password": "hashed_pw",
            "full_name": "Preservation User",
            "status": "active",
            "roles": ["member"],
            "created_at": now_iso,
            "updated_at": now_iso,
            "failed_login_attempts": 0,
            "require_password_change": False,
            "email_verified": True,
            "is_admin": False,
        }
    }
    repo = _make_repo(table)

    result = await repo.find_by_id(user_id)

    assert result is not None
    assert result.id == user_id
    assert result.email == "preserve@example.com"
    assert result.full_name == "Preservation User"
    assert result.status == UserStatus.ACTIVE
    assert UserRole.MEMBER in result.roles
