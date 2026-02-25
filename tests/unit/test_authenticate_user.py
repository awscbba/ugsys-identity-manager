"""Unit tests for AuthService.authenticate."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import AuthenticationError
from src.domain.value_objects.password_validator import PasswordValidator


def make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    return User(
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test",
        status=status,
        roles=[UserRole.MEMBER],
    )


@pytest.fixture
def deps() -> tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator]:
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    token_blacklist = AsyncMock()
    password_validator = PasswordValidator()
    token_svc.create_access_token.return_value = "access"
    token_svc.create_refresh_token.return_value = "refresh"
    hasher.verify.return_value = True
    return repo, token_svc, hasher, token_blacklist, password_validator


@pytest.mark.asyncio
async def test_login_success(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    repo.find_by_email.return_value = make_user()
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    result = await svc.authenticate(AuthenticateCommand(email="user@example.com", password="pw"))
    assert result.access_token == "access"
    assert result.refresh_token == "refresh"


@pytest.mark.asyncio
async def test_login_wrong_password(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    repo.find_by_email.return_value = make_user()
    hasher.verify.return_value = False
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(AuthenticationError):
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="wrong"))


@pytest.mark.asyncio
async def test_login_user_not_found(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    repo.find_by_email.return_value = None
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(AuthenticationError):
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="pw"))
