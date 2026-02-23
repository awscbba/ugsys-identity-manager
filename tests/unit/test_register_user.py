"""Unit tests for RegisterUserUseCase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.register_user import RegisterUserCommand, RegisterUserUseCase
from src.domain.entities.user import User


@pytest.fixture
def user_repo():
    repo = AsyncMock()
    repo.find_by_email.return_value = None
    repo.save.side_effect = lambda u: u
    return repo


@pytest.fixture
def password_hasher():
    hasher = MagicMock()
    hasher.hash.return_value = "hashed_pw"
    return hasher


@pytest.mark.asyncio
async def test_register_new_user(user_repo, password_hasher):
    use_case = RegisterUserUseCase(user_repo, password_hasher)
    cmd = RegisterUserCommand(email="test@example.com", password="secret", full_name="Test User")
    user = await use_case.execute(cmd)
    assert user.email == "test@example.com"
    assert user.hashed_password == "hashed_pw"
    user_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(user_repo, password_hasher):
    user_repo.find_by_email.return_value = MagicMock(spec=User)
    use_case = RegisterUserUseCase(user_repo, password_hasher)
    cmd = RegisterUserCommand(email="dup@example.com", password="secret", full_name="Dup")
    with pytest.raises(ValueError, match="already registered"):
        await use_case.execute(cmd)
