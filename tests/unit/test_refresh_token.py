"""Unit tests for refresh token flow."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserStatus


@pytest.fixture
def active_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=UserStatus.ACTIVE,
    )


@pytest.fixture
def auth_service(active_user: User) -> AuthService:
    repo = AsyncMock()
    repo.find_by_id.return_value = active_user
    token_svc = MagicMock()
    token_svc.verify_token.return_value = {"sub": str(active_user.id), "type": "refresh"}
    token_svc.create_access_token.return_value = "new_access"
    token_svc.create_refresh_token.return_value = "new_refresh"
    hasher = MagicMock()
    return AuthService(user_repo=repo, token_service=token_svc, password_hasher=hasher)


async def test_refresh_returns_new_token_pair(auth_service: AuthService) -> None:
    result = await auth_service.refresh(RefreshTokenCommand(refresh_token="valid_refresh"))
    assert result.access_token == "new_access"
    assert result.refresh_token == "new_refresh"


async def test_refresh_rejects_invalid_token(active_user: User) -> None:
    repo = AsyncMock()
    token_svc = MagicMock()
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = AuthService(user_repo=repo, token_service=token_svc, password_hasher=MagicMock())
    with pytest.raises(ValueError, match="Invalid or expired"):
        await svc.refresh(RefreshTokenCommand(refresh_token="bad"))


async def test_refresh_rejects_access_token_used_as_refresh(active_user: User) -> None:
    repo = AsyncMock()
    token_svc = MagicMock()
    token_svc.verify_token.return_value = {"sub": str(active_user.id), "type": "access"}
    svc = AuthService(user_repo=repo, token_service=token_svc, password_hasher=MagicMock())
    with pytest.raises(ValueError, match="not a refresh token"):
        await svc.refresh(RefreshTokenCommand(refresh_token="access_token"))
