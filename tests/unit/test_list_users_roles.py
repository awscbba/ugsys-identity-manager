"""Unit tests for UserService.list_users and get_user_roles."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus


def make_user(roles: list[UserRole] | None = None) -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test",
        status=UserStatus.ACTIVE,
        roles=roles or [UserRole.MEMBER],
    )


@pytest.mark.asyncio
async def test_list_users_admin_succeeds() -> None:
    repo = AsyncMock()
    users = [make_user(), make_user()]
    repo.list_all.return_value = users
    svc = UserService(user_repo=repo)
    result = await svc.list_users(requester_id=str(uuid4()), is_admin=True)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_users_non_admin_raises() -> None:
    repo = AsyncMock()
    svc = UserService(user_repo=repo)
    with pytest.raises(PermissionError, match="Admin access required"):
        await svc.list_users(requester_id=str(uuid4()), is_admin=False)


@pytest.mark.asyncio
async def test_get_user_roles_own_profile() -> None:
    repo = AsyncMock()
    user = make_user(roles=[UserRole.MEMBER, UserRole.ADMIN])
    repo.find_by_id.return_value = user
    svc = UserService(user_repo=repo)
    result = await svc.get_user_roles(user_id=user.id, requester_id=str(user.id), is_admin=False)
    assert UserRole.MEMBER in result
    assert UserRole.ADMIN in result


@pytest.mark.asyncio
async def test_get_user_roles_admin_can_query_any() -> None:
    repo = AsyncMock()
    user = make_user()
    repo.find_by_id.return_value = user
    svc = UserService(user_repo=repo)
    result = await svc.get_user_roles(user_id=user.id, requester_id=str(uuid4()), is_admin=True)
    assert result == [UserRole.MEMBER]


@pytest.mark.asyncio
async def test_get_user_roles_non_admin_other_user_raises() -> None:
    repo = AsyncMock()
    user = make_user()
    repo.find_by_id.return_value = user
    svc = UserService(user_repo=repo)
    with pytest.raises(PermissionError, match="Access denied"):
        await svc.get_user_roles(user_id=user.id, requester_id=str(uuid4()), is_admin=False)


@pytest.mark.asyncio
async def test_get_user_roles_not_found_raises() -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    svc = UserService(user_repo=repo)
    with pytest.raises(ValueError, match="not found"):
        await svc.get_user_roles(user_id=uuid4(), requester_id=str(uuid4()), is_admin=True)
