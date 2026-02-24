"""Unit tests for AuthService.forgot_password and reset_password."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus


def make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    return User(
        id=uuid4(),
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
    hasher.hash.return_value = "new_hashed"
    hasher.verify.return_value = True
    return repo, token_svc, hasher


@pytest.mark.asyncio
async def test_forgot_password_known_email_returns_token(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    user = make_user()
    repo.find_by_email.return_value = user
    token_svc.create_password_reset_token.return_value = "reset-token"
    svc = AuthService(repo, token_svc, hasher)
    result = await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))
    assert result == "reset-token"
    token_svc.create_password_reset_token.assert_called_once_with(user_id=user.id, email=user.email)


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_none(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    repo.find_by_email.return_value = None
    svc = AuthService(repo, token_svc, hasher)
    result = await svc.forgot_password(ForgotPasswordCommand(email="nobody@example.com"))
    assert result is None
    token_svc.create_password_reset_token.assert_not_called()


@pytest.mark.asyncio
async def test_reset_password_success(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_id.return_value = user
    repo.update.return_value = user
    token_svc.verify_token.return_value = {
        "sub": str(user.id),
        "email": user.email,
        "type": "password_reset",
    }
    svc = AuthService(repo, token_svc, hasher)
    await svc.reset_password(ResetPasswordCommand(token="valid-token", new_password="newpass"))
    repo.update.assert_called_once()
    assert user.status == UserStatus.ACTIVE  # auto-activated


@pytest.mark.asyncio
async def test_reset_password_invalid_token_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = AuthService(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="Invalid or expired reset token"):
        await svc.reset_password(ResetPasswordCommand(token="bad", new_password="x"))


@pytest.mark.asyncio
async def test_reset_password_wrong_token_type_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    token_svc.verify_token.return_value = {"sub": str(uuid4()), "type": "access"}
    svc = AuthService(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="Invalid token type"):
        await svc.reset_password(ResetPasswordCommand(token="wrong-type", new_password="x"))
