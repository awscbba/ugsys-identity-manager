"""Unit tests for UserService admin/RBAC use cases."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.commands.update_user import (
    AssignRoleCommand,
    DeactivateUserCommand,
    RemoveRoleCommand,
    UpdateProfileCommand,
)
from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus


def _make_user(**kwargs) -> User:  # type: ignore[no-untyped-def]
    defaults = dict(
        email="test@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=UserStatus.ACTIVE,
        roles=[UserRole.MEMBER],
    )
    defaults.update(kwargs)
    return User(**defaults)


@pytest.fixture
def repo() -> AsyncMock:
    r = AsyncMock()
    r.update = AsyncMock(side_effect=lambda u: u)
    return r


@pytest.fixture
def events() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(repo: AsyncMock, events: MagicMock) -> UserService:
    return UserService(user_repo=repo, event_publisher=events)


# ── update_profile ────────────────────────────────────────────────────────────


async def test_update_profile_success(service: UserService, repo: AsyncMock) -> None:
    user = _make_user()
    repo.find_by_id = AsyncMock(return_value=user)
    updated = await service.update_profile(
        UpdateProfileCommand(user_id=user.id, requester_id=str(user.id), full_name="New Name")
    )
    assert updated.full_name == "New Name"


async def test_update_profile_forbidden(service: UserService, repo: AsyncMock) -> None:
    user = _make_user()
    repo.find_by_id = AsyncMock(return_value=user)
    with pytest.raises(PermissionError):
        await service.update_profile(
            UpdateProfileCommand(user_id=user.id, requester_id=str(uuid4()), full_name="X")
        )


async def test_update_profile_not_found(service: UserService, repo: AsyncMock) -> None:
    repo.find_by_id = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="not found"):
        await service.update_profile(
            UpdateProfileCommand(user_id=uuid4(), requester_id=str(uuid4()), full_name="X")
        )


# ── assign_role ───────────────────────────────────────────────────────────────


async def test_assign_role_success(
    service: UserService, repo: AsyncMock, events: MagicMock
) -> None:
    user = _make_user()
    repo.find_by_id = AsyncMock(return_value=user)
    updated = await service.assign_role(
        AssignRoleCommand(user_id=user.id, role=UserRole.ADMIN, requester_id=str(uuid4()))
    )
    assert UserRole.ADMIN in updated.roles
    events.publish.assert_called_once()
    call_kwargs = events.publish.call_args
    assert call_kwargs.kwargs["detail_type"] == "identity.user.role_changed"
    assert call_kwargs.kwargs["detail"]["action"] == "assigned"


async def test_assign_role_not_found(service: UserService, repo: AsyncMock) -> None:
    repo.find_by_id = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="not found"):
        await service.assign_role(
            AssignRoleCommand(user_id=uuid4(), role=UserRole.ADMIN, requester_id=str(uuid4()))
        )


# ── remove_role ───────────────────────────────────────────────────────────────


async def test_remove_role_success(
    service: UserService, repo: AsyncMock, events: MagicMock
) -> None:
    user = _make_user(roles=[UserRole.MEMBER, UserRole.ADMIN])
    repo.find_by_id = AsyncMock(return_value=user)
    updated = await service.remove_role(
        RemoveRoleCommand(user_id=user.id, role=UserRole.ADMIN, requester_id=str(uuid4()))
    )
    assert UserRole.ADMIN not in updated.roles
    events.publish.assert_called_once()
    assert events.publish.call_args.kwargs["detail"]["action"] == "removed"


# ── deactivate ────────────────────────────────────────────────────────────────


async def test_deactivate_success(service: UserService, repo: AsyncMock, events: MagicMock) -> None:
    user = _make_user()
    repo.find_by_id = AsyncMock(return_value=user)
    updated = await service.deactivate(
        DeactivateUserCommand(user_id=user.id, requester_id=str(uuid4()))
    )
    assert updated.status == UserStatus.INACTIVE
    events.publish.assert_called_once()
    assert events.publish.call_args.kwargs["detail_type"] == "identity.user.deleted"


async def test_deactivate_not_found(service: UserService, repo: AsyncMock) -> None:
    repo.find_by_id = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="not found"):
        await service.deactivate(DeactivateUserCommand(user_id=uuid4(), requester_id=str(uuid4())))
