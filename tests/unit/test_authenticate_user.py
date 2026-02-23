"""Unit tests for AuthenticateUserUseCase."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.authenticate_user import AuthenticateCommand, AuthenticateUserUseCase
from src.domain.entities.user import User, UserRole, UserStatus


def make_user(status=UserStatus.ACTIVE):
    return User(
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test",
        status=status,
        roles=[UserRole.MEMBER],
    )


@pytest.fixture
def deps():
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    token_svc.create_access_token.return_value = "access"
    token_svc.create_refresh_token.return_value = "refresh"
    hasher.verify.return_value = True
    return repo, token_svc, hasher


@pytest.mark.asyncio
async def test_login_success(deps):
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user()
    uc = AuthenticateUserUseCase(repo, token_svc, hasher)
    result = await uc.execute(AuthenticateCommand(email="user@example.com", password="pw"))
    assert result.access_token == "access"
    assert result.refresh_token == "refresh"


@pytest.mark.asyncio
async def test_login_wrong_password(deps):
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user()
    hasher.verify.return_value = False
    uc = AuthenticateUserUseCase(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="Invalid credentials"):
        await uc.execute(AuthenticateCommand(email="user@example.com", password="wrong"))


@pytest.mark.asyncio
async def test_login_inactive_user(deps):
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = make_user(status=UserStatus.INACTIVE)
    uc = AuthenticateUserUseCase(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="not active"):
        await uc.execute(AuthenticateCommand(email="user@example.com", password="pw"))
