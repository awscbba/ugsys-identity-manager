"""Unit tests for UserService.list_users and get_user_roles."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.queries.list_users import ListUsersQuery
from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import AuthorizationError, NotFoundError


def make_user(roles: list[UserRole] | None = None) -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test",
        status=UserStatus.ACTIVE,
        roles=roles or [UserRole.MEMBER],
    )


def make_admin() -> User:
    return User(
        id=uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin",
        status=UserStatus.ACTIVE,
        roles=[UserRole.ADMIN],
    )


@pytest.mark.asyncio
async def test_list_users_admin_succeeds() -> None:
    admin = make_admin()
    users = [make_user(), make_user()]
    repo = AsyncMock()
    repo.find_by_id.return_value = admin
    repo.list_paginated.return_value = (users, 2)
    svc = UserService(user_repo=repo)
    result, total = await svc.list_users(ListUsersQuery(admin_id=str(admin.id)))
    assert len(result) == 2
    assert total == 2


@pytest.mark.asyncio
async def test_list_users_non_admin_raises() -> None:
    non_admin = make_user()
    repo = AsyncMock()
    repo.find_by_id.return_value = non_admin
    svc = UserService(user_repo=repo)
    with pytest.raises(AuthorizationError):
        await svc.list_users(ListUsersQuery(admin_id=str(non_admin.id)))


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
    with pytest.raises(AuthorizationError):
        await svc.get_user_roles(user_id=user.id, requester_id=str(uuid4()), is_admin=False)


@pytest.mark.asyncio
async def test_get_user_roles_not_found_raises() -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    svc = UserService(user_repo=repo)
    with pytest.raises(NotFoundError):
        await svc.get_user_roles(user_id=uuid4(), requester_id=str(uuid4()), is_admin=True)
