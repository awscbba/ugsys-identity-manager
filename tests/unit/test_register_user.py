"""Unit tests for AuthService.register."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.register_user import RegisterUserCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserStatus
from src.domain.exceptions import ConflictError, ValidationError
from src.domain.value_objects.password_validator import PasswordValidator


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


@pytest.fixture
def token_blacklist() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def password_validator() -> PasswordValidator:
    return PasswordValidator()


@pytest.mark.asyncio
async def test_register_new_user(
    user_repo: AsyncMock,
    password_hasher: MagicMock,
    token_service: MagicMock,
    token_blacklist: AsyncMock,
    password_validator: PasswordValidator,
) -> None:
    service = AuthService(
        user_repo, token_service, password_hasher, token_blacklist, password_validator
    )
    cmd = RegisterUserCommand(
        email="test@example.com", password="Str0ng!Pass", full_name="Test User"
    )
    user = await service.register(cmd)
    assert user.email == "test@example.com"
    assert user.hashed_password == "hashed_pw"
    assert user.status == UserStatus.PENDING_VERIFICATION
    assert user.email_verification_token is not None
    user_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(
    user_repo: AsyncMock,
    password_hasher: MagicMock,
    token_service: MagicMock,
    token_blacklist: AsyncMock,
    password_validator: PasswordValidator,
) -> None:
    user_repo.find_by_email.return_value = MagicMock(spec=User)
    service = AuthService(
        user_repo, token_service, password_hasher, token_blacklist, password_validator
    )
    cmd = RegisterUserCommand(email="dup@example.com", password="Str0ng!Pass", full_name="Dup")
    with pytest.raises(ConflictError) as exc_info:
        await service.register(cmd)
    assert exc_info.value.error_code == "EMAIL_ALREADY_EXISTS"
    assert "already in use" in exc_info.value.user_message


@pytest.mark.asyncio
async def test_register_weak_password(
    user_repo: AsyncMock,
    password_hasher: MagicMock,
    token_service: MagicMock,
    token_blacklist: AsyncMock,
    password_validator: PasswordValidator,
) -> None:
    service = AuthService(
        user_repo, token_service, password_hasher, token_blacklist, password_validator
    )
    cmd = RegisterUserCommand(email="test@example.com", password="weak", full_name="Test")
    with pytest.raises(ValidationError) as exc_info:
        await service.register(cmd)
    assert exc_info.value.error_code == "WEAK_PASSWORD"
    assert "violations" in exc_info.value.additional_data
