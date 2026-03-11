"""Unit tests for the 'already locked' pre-check path in AuthService.authenticate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import AccountLockedError
from src.domain.value_objects.password_validator import PasswordValidator


def _make_locked_user() -> User:
    """Return a user whose account is already locked (locked_until is in the future)."""
    user = User(
        email="locked@example.com",
        hashed_password="hashed",
        full_name="Locked User",
        status=UserStatus.ACTIVE,
        roles=[UserRole.MEMBER],
    )
    user.failed_login_attempts = 5
    user.account_locked_until = datetime.now(UTC) + timedelta(minutes=15)
    return user


def _make_service(repo: AsyncMock) -> AuthService:
    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock()
    hasher = MagicMock()
    hasher.verify.return_value = True
    blacklist = AsyncMock()
    return AuthService(
        user_repo=repo,
        token_service=token_svc,
        password_hasher=hasher,
        token_blacklist=blacklist,
        password_validator=PasswordValidator(),
    )


async def test_already_locked_account_raises_423_before_password_check() -> None:
    """If account_locked_until is in the future, must raise AccountLockedError immediately
    without ever checking the password."""
    repo = AsyncMock()
    user = _make_locked_user()
    repo.find_by_email.return_value = user

    hasher = MagicMock()
    svc = AuthService(
        user_repo=repo,
        token_service=MagicMock(),
        password_hasher=hasher,
        token_blacklist=AsyncMock(),
        password_validator=PasswordValidator(),
    )

    with pytest.raises(AccountLockedError) as exc_info:
        await svc.authenticate(AuthenticateCommand(email="locked@example.com", password="any"))

    assert exc_info.value.error_code == "ACCOUNT_LOCKED"
    assert exc_info.value.additional_data["retry_after_seconds"] > 0
    # Password hasher must NOT have been called — lockout check is pre-password
    hasher.verify.assert_not_called()


async def test_already_locked_retry_after_is_positive() -> None:
    """retry_after_seconds must reflect the remaining lock duration."""
    repo = AsyncMock()
    user = _make_locked_user()
    # Lock for exactly 10 minutes from now
    user.account_locked_until = datetime.now(UTC) + timedelta(minutes=10)
    repo.find_by_email.return_value = user

    svc = _make_service(repo)

    with pytest.raises(AccountLockedError) as exc_info:
        await svc.authenticate(AuthenticateCommand(email="locked@example.com", password="any"))

    retry = exc_info.value.additional_data["retry_after_seconds"]
    # Should be roughly 600 seconds (10 min), allow ±5s for test execution time
    assert 595 <= retry <= 605


async def test_refresh_inactive_user_raises_invalid_token() -> None:
    """refresh() must raise INVALID_TOKEN when the user is found but inactive."""
    from src.application.commands.refresh_token import RefreshTokenCommand
    from src.domain.exceptions import AuthenticationError

    user_id = __import__("uuid").uuid4()
    inactive_user = User(
        id=user_id,
        email="inactive@example.com",
        hashed_password="h",
        full_name="Inactive",
        status=UserStatus.INACTIVE,
        roles=[UserRole.MEMBER],
    )

    repo = AsyncMock()
    repo.find_by_id.return_value = inactive_user

    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"sub": str(user_id), "type": "refresh"})

    svc = AuthService(
        user_repo=repo,
        token_service=token_svc,
        password_hasher=MagicMock(),
        token_blacklist=AsyncMock(),
        password_validator=PasswordValidator(),
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await svc.refresh(RefreshTokenCommand(refresh_token="valid-refresh"))

    assert exc_info.value.error_code == "INVALID_TOKEN"


async def test_refresh_user_not_found_raises_invalid_token() -> None:
    """refresh() must raise INVALID_TOKEN when the user_id in the token doesn't exist."""
    from src.application.commands.refresh_token import RefreshTokenCommand
    from src.domain.exceptions import AuthenticationError

    user_id = __import__("uuid").uuid4()
    repo = AsyncMock()
    repo.find_by_id.return_value = None

    token_svc = MagicMock()
    token_svc.verify_token = AsyncMock(return_value={"sub": str(user_id), "type": "refresh"})

    svc = AuthService(
        user_repo=repo,
        token_service=token_svc,
        password_hasher=MagicMock(),
        token_blacklist=AsyncMock(),
        password_validator=PasswordValidator(),
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await svc.refresh(RefreshTokenCommand(refresh_token="valid-refresh"))

    assert exc_info.value.error_code == "INVALID_TOKEN"
