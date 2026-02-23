"""Unit tests for AuthService.register."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.register_user import RegisterUserCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User


@pytest.fixture
def user_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_email.return_value = None
    repo.save.side_effect = lambda u: u
    return repo


@pytest.fixture
def password_hasher() -> MagicMock:
    hasher = MagicMock()
    hasher.hash.return_value = "hashed_pw"
    hasher.verify.return_value = True
    return hasher


@pytest.fixture
def token_service() -> MagicMock:
    svc = MagicMock()
    svc.create_access_token.return_value = "access"
    svc.create_refresh_token.return_value = "refresh"
    return svc


@pytest.mark.asyncio
async def test_register_new_user(
    user_repo: AsyncMock, password_hasher: MagicMock, token_service: MagicMock
) -> None:
    service = AuthService(user_repo, token_service, password_hasher)
    cmd = RegisterUserCommand(email="test@example.com", password="secret", full_name="Test User")
    user = await service.register(cmd)
    assert user.email == "test@example.com"
    assert user.hashed_password == "hashed_pw"
    user_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(
    user_repo: AsyncMock, password_hasher: MagicMock, token_service: MagicMock
) -> None:
    user_repo.find_by_email.return_value = MagicMock(spec=User)
    service = AuthService(user_repo, token_service, password_hasher)
    cmd = RegisterUserCommand(email="dup@example.com", password="secret", full_name="Dup")
    with pytest.raises(ValueError, match="already registered"):
        await service.register(cmd)
