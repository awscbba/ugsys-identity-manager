"""Unit tests for UserService."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.commands.admin_user import (
    ActivateUserCommand,
    RequirePasswordChangeCommand,
    SuspendUserCommand,
)
from src.application.queries.get_user import GetUserQuery
from src.application.queries.list_users import ListUsersQuery
from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import AuthorizationError, NotFoundError


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


@pytest.fixture
def admin_user() -> User:
    return User(
        id=uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin User",
        status=UserStatus.ACTIVE,
        roles=[UserRole.ADMIN],
    )


# ── get_user ──────────────────────────────────────────────────────────────────


async def test_get_own_profile(active_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    svc = UserService(user_repo=repo)
    result = await svc.get_user(
        GetUserQuery(user_id=active_user.id, requester_id=str(active_user.id))
    )
    assert result.id == active_user.id


async def test_get_other_user_as_non_admin_raises_authorization_error(active_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    svc = UserService(user_repo=repo)
    with pytest.raises(AuthorizationError):
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


async def test_get_nonexistent_user_raises_not_found() -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    svc = UserService(user_repo=repo)
    with pytest.raises(NotFoundError):
        await svc.get_user(GetUserQuery(user_id=uuid4(), requester_id=str(uuid4()), is_admin=True))


# ── suspend_user ──────────────────────────────────────────────────────────────


async def test_suspend_user_sets_inactive(active_user: User, admin_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.side_effect = lambda uid: admin_user if uid == admin_user.id else active_user
    repo.update.side_effect = lambda u: u
    events = AsyncMock()
    svc = UserService(user_repo=repo, event_publisher=events)

    result = await svc.suspend_user(
        SuspendUserCommand(user_id=active_user.id, admin_id=str(admin_user.id))
    )

    assert result.status == UserStatus.INACTIVE
    events.publish.assert_awaited_once_with(
        detail_type="identity.user.deactivated",
        payload={"user_id": str(active_user.id), "email": active_user.email},
    )


async def test_suspend_user_non_admin_raises(active_user: User) -> None:
    non_admin = User(
        id=uuid4(),
        email="nonadmin@example.com",
        hashed_password="h",
        full_name="Non Admin",
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.return_value = non_admin
    svc = UserService(user_repo=repo)

    with pytest.raises(AuthorizationError):
        await svc.suspend_user(
            SuspendUserCommand(user_id=active_user.id, admin_id=str(non_admin.id))
        )


async def test_suspend_nonexistent_user_raises(admin_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.side_effect = lambda uid: admin_user if uid == admin_user.id else None
    svc = UserService(user_repo=repo)

    with pytest.raises(NotFoundError):
        await svc.suspend_user(SuspendUserCommand(user_id=uuid4(), admin_id=str(admin_user.id)))


# ── activate_user ─────────────────────────────────────────────────────────────


async def test_activate_user_sets_active(admin_user: User) -> None:
    target = User(
        id=uuid4(),
        email="target@example.com",
        hashed_password="h",
        full_name="Target",
        status=UserStatus.INACTIVE,
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.side_effect = lambda uid: admin_user if uid == admin_user.id else target
    repo.update.side_effect = lambda u: u
    events = AsyncMock()
    svc = UserService(user_repo=repo, event_publisher=events)

    result = await svc.activate_user(
        ActivateUserCommand(user_id=target.id, admin_id=str(admin_user.id))
    )

    assert result.status == UserStatus.ACTIVE
    events.publish.assert_awaited_once_with(
        detail_type="identity.user.activated",
        payload={"user_id": str(target.id), "email": target.email},
    )


async def test_activate_user_non_admin_raises() -> None:
    non_admin = User(
        id=uuid4(),
        email="nonadmin@example.com",
        hashed_password="h",
        full_name="Non Admin",
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.return_value = non_admin
    svc = UserService(user_repo=repo)

    with pytest.raises(AuthorizationError):
        await svc.activate_user(ActivateUserCommand(user_id=uuid4(), admin_id=str(non_admin.id)))


# ── require_password_change ───────────────────────────────────────────────────


async def test_require_password_change_sets_flag(admin_user: User) -> None:
    target = User(
        id=uuid4(),
        email="target@example.com",
        hashed_password="h",
        full_name="Target",
        status=UserStatus.ACTIVE,
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.side_effect = lambda uid: admin_user if uid == admin_user.id else target
    repo.update.side_effect = lambda u: u
    svc = UserService(user_repo=repo)

    result = await svc.require_password_change(
        RequirePasswordChangeCommand(user_id=target.id, admin_id=str(admin_user.id))
    )

    assert result.require_password_change is True


async def test_require_password_change_non_admin_raises() -> None:
    non_admin = User(
        id=uuid4(),
        email="nonadmin@example.com",
        hashed_password="h",
        full_name="Non Admin",
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.return_value = non_admin
    svc = UserService(user_repo=repo)

    with pytest.raises(AuthorizationError):
        await svc.require_password_change(
            RequirePasswordChangeCommand(user_id=uuid4(), admin_id=str(non_admin.id))
        )


# ── list_users ────────────────────────────────────────────────────────────────


async def test_list_users_returns_paginated_results(admin_user: User) -> None:
    users_page = [
        User(id=uuid4(), email=f"u{i}@example.com", hashed_password="h", full_name=f"User {i}")
        for i in range(3)
    ]
    repo = AsyncMock()
    repo.find_by_id.return_value = admin_user
    repo.list_paginated.return_value = (users_page, 25)
    svc = UserService(user_repo=repo)

    users, total = await svc.list_users(
        ListUsersQuery(page=1, page_size=20, admin_id=str(admin_user.id))
    )

    assert len(users) == 3
    assert total == 25
    repo.list_paginated.assert_awaited_once_with(
        page=1,
        page_size=20,
        status_filter=None,
        role_filter=None,
    )


async def test_list_users_caps_page_size_at_100(admin_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = admin_user
    repo.list_paginated.return_value = ([], 0)
    svc = UserService(user_repo=repo)

    await svc.list_users(ListUsersQuery(page=1, page_size=500, admin_id=str(admin_user.id)))

    repo.list_paginated.assert_awaited_once_with(
        page=1,
        page_size=100,
        status_filter=None,
        role_filter=None,
    )


async def test_list_users_passes_filters(admin_user: User) -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = admin_user
    repo.list_paginated.return_value = ([], 0)
    svc = UserService(user_repo=repo)

    await svc.list_users(
        ListUsersQuery(
            page=2,
            page_size=10,
            admin_id=str(admin_user.id),
            status_filter="active",
            role_filter="admin",
        )
    )

    repo.list_paginated.assert_awaited_once_with(
        page=2,
        page_size=10,
        status_filter="active",
        role_filter="admin",
    )


async def test_list_users_non_admin_raises() -> None:
    non_admin = User(
        id=uuid4(),
        email="nonadmin@example.com",
        hashed_password="h",
        full_name="Non Admin",
        roles=[UserRole.MEMBER],
    )
    repo = AsyncMock()
    repo.find_by_id.return_value = non_admin
    svc = UserService(user_repo=repo)

    with pytest.raises(AuthorizationError):
        await svc.list_users(ListUsersQuery(page=1, page_size=20, admin_id=str(non_admin.id)))
