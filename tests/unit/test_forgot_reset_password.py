"""Unit tests for AuthService.forgot_password and reset_password."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import AuthenticationError, NotFoundError, ValidationError
from src.domain.value_objects.password_validator import PasswordValidator


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
def deps() -> tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator]:
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    token_blacklist = AsyncMock()
    password_validator = PasswordValidator()
    hasher.hash.return_value = "new_hashed"
    hasher.verify.return_value = True
    return repo, token_svc, hasher, token_blacklist, password_validator


@pytest.mark.asyncio
async def test_forgot_password_known_email_returns_token(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    user = make_user()
    repo.find_by_email.return_value = user
    token_svc.create_password_reset_token.return_value = "reset-token"
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    result = await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))
    assert result == "reset-token"
    token_svc.create_password_reset_token.assert_called_once_with(user_id=user.id, email=user.email)


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_none(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    repo.find_by_email.return_value = None
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    result = await svc.forgot_password(ForgotPasswordCommand(email="nobody@example.com"))
    assert result is None
    token_svc.create_password_reset_token.assert_not_called()


@pytest.mark.asyncio
async def test_reset_password_success(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_id.return_value = user
    repo.update.return_value = user
    token_svc.verify_token.return_value = {
        "sub": str(user.id),
        "email": user.email,
        "type": "password_reset",
    }
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    await svc.reset_password(ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass"))
    repo.update.assert_called_once()
    assert user.status == UserStatus.ACTIVE  # auto-activated
    assert user.require_password_change is False
    assert user.last_password_change is not None


@pytest.mark.asyncio
async def test_reset_password_invalid_token_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(AuthenticationError) as exc_info:
        await svc.reset_password(ResetPasswordCommand(token="bad", new_password="Str0ng!Pass"))
    assert exc_info.value.error_code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_reset_password_wrong_token_type_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.verify_token.return_value = {"sub": str(uuid4()), "type": "access"}
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(AuthenticationError) as exc_info:
        await svc.reset_password(
            ResetPasswordCommand(token="wrong-type", new_password="Str0ng!Pass")
        )
    assert exc_info.value.error_code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_reset_password_user_not_found_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.verify_token.return_value = {
        "sub": str(uuid4()),
        "type": "password_reset",
    }
    repo.find_by_id.return_value = None
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(NotFoundError) as exc_info:
        await svc.reset_password(
            ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
        )
    assert exc_info.value.error_code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_reset_password_weak_password_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    user = make_user()
    repo.find_by_id.return_value = user
    token_svc.verify_token.return_value = {
        "sub": str(user.id),
        "type": "password_reset",
    }
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    with pytest.raises(ValidationError) as exc_info:
        await svc.reset_password(ResetPasswordCommand(token="valid-token", new_password="weak"))
    assert exc_info.value.error_code == "WEAK_PASSWORD"
    assert "violations" in exc_info.value.additional_data


@pytest.mark.asyncio
async def test_reset_password_publishes_event(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    user = make_user()
    repo.find_by_id.return_value = user
    repo.update.return_value = user
    token_svc.verify_token.return_value = {
        "sub": str(user.id),
        "type": "password_reset",
    }
    event_publisher = AsyncMock()
    svc = AuthService(
        repo,
        token_svc,
        hasher,
        token_blacklist,
        password_validator,
        event_publisher=event_publisher,
    )
    await svc.reset_password(ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass"))
    event_publisher.publish.assert_called_once_with(
        detail_type="identity.auth.password_changed",
        payload={"user_id": str(user.id), "email": user.email},
    )
