"""Unit tests for UserService."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.queries.get_user import GetUserQuery
from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus


@pytest.fixture
def active_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=UserStatus.ACTIVE,
        roles=[UserRole.MEMBER],
    )


async def test_get_own_profile(active_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    svc = UserService(user_repo=repo)
    result = await svc.get_user(
        GetUserQuery(user_id=active_user.id, requester_id=str(active_user.id))
    )
    assert result.id == active_user.id


async def test_get_other_user_as_non_admin_raises(active_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    svc = UserService(user_repo=repo)
    with pytest.raises(PermissionError, match="Access denied"):
        await svc.get_user(
            GetUserQuery(user_id=active_user.id, requester_id=str(uuid4()), is_admin=False)
        )


async def test_admin_can_get_any_user(active_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    svc = UserService(user_repo=repo)
    result = await svc.get_user(
        GetUserQuery(user_id=active_user.id, requester_id=str(uuid4()), is_admin=True)
    )
    assert result.id == active_user.id


async def test_get_nonexistent_user_raises() -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    svc = UserService(user_repo=repo)
    with pytest.raises(ValueError, match="not found"):
        await svc.get_user(GetUserQuery(user_id=uuid4(), requester_id=str(uuid4()), is_admin=True))
