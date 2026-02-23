"""Unit tests for AuthService.authenticate."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus


def make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    return User(
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test",
        status=status,
        roles=[UserRole.MEMBER],
    )


@pytest.fixture
def deps() -> tuple[AsyncMock, MagicMock, MagicMock]:
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    token_svc.create_access_token.return_value = "access"
    token_svc.create_refresh_token.return_value = "refresh"
    hasher.verify.return_value = True
    return repo, token_svc, hasher


@pytest.mark.asyncio
async def test_login_success(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user()
    svc = AuthService(repo, token_svc, hasher)
    result = await svc.authenticate(AuthenticateCommand(email="user@example.com", password="pw"))
    assert result.access_token == "access"
    assert result.refresh_token == "refresh"


@pytest.mark.asyncio
async def test_login_wrong_password(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user()
    hasher.verify.return_value = False
    svc = AuthService(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="Invalid credentials"):
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="wrong"))


@pytest.mark.asyncio
async def test_login_inactive_user(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user(status=UserStatus.INACTIVE)
    svc = AuthService(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="not active"):
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="pw"))
