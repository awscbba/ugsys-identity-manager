"""Unit tests for AuthService: verify_email, resend_verification, logout, and event branches."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.authenticate_user import AuthenticateCommand
from src.application.commands.logout import LogoutCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.resend_verification import ResendVerificationCommand
from src.application.commands.verify_email import VerifyEmailCommand
from src.application.services.auth_service import AuthService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    ConflictError,
    ValidationError,
)
from src.domain.value_objects.password_validator import PasswordValidator

# ─── Helpers ──────────────────────────────────────────────────────────────────


def make_user(
    status: UserStatus = UserStatus.ACTIVE,
    email_verified: bool = False,
    updated_at: datetime | None = None,
) -> User:
    u = User(
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=status,
        roles=[UserRole.MEMBER],
    )
    if updated_at is not None:
        u.updated_at = updated_at
    u.email_verified = email_verified
    return u


def make_service(
    repo: AsyncMock,
    token_svc: MagicMock | None = None,
    hasher: MagicMock | None = None,
    blacklist: AsyncMock | None = None,
    events: AsyncMock | None = None,
) -> AuthService:
    if token_svc is None:
        token_svc = MagicMock()
        token_svc.create_access_token.return_value = "access"
        token_svc.create_refresh_token.return_value = "refresh"
    if hasher is None:
        hasher = MagicMock()
        hasher.verify.return_value = True
        hasher.hash.return_value = "hashed_pw"  # gitguardian:ignore
    if blacklist is None:
        blacklist = AsyncMock()
    return AuthService(
        user_repo=repo,
        token_service=token_svc,
        password_hasher=hasher,
        token_blacklist=blacklist,
        password_validator=PasswordValidator(),
        event_publisher=events,
    )


# ─── verify_email ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_email_token_not_found() -> None:
    repo = AsyncMock()
    repo.find_by_verification_token.return_value = None
    svc = make_service(repo)

    with pytest.raises(ValidationError) as exc_info:
        await svc.verify_email(VerifyEmailCommand(token="bad-token"))

    assert exc_info.value.error_code == "INVALID_VERIFICATION_TOKEN"


@pytest.mark.asyncio
async def test_verify_email_already_verified_flag() -> None:
    repo = AsyncMock()
    user = make_user(status=UserStatus.PENDING_VERIFICATION, email_verified=True)
    repo.find_by_verification_token.return_value = user
    svc = make_service(repo)

    with pytest.raises(ConflictError) as exc_info:
        await svc.verify_email(VerifyEmailCommand(token="tok"))

    assert exc_info.value.error_code == "ALREADY_VERIFIED"


@pytest.mark.asyncio
async def test_verify_email_already_active_status() -> None:
    repo = AsyncMock()
    user = make_user(status=UserStatus.ACTIVE, email_verified=False)
    repo.find_by_verification_token.return_value = user
    svc = make_service(repo)

    with pytest.raises(ConflictError) as exc_info:
        await svc.verify_email(VerifyEmailCommand(token="tok"))

    assert exc_info.value.error_code == "ALREADY_VERIFIED"


@pytest.mark.asyncio
async def test_verify_email_token_expired() -> None:
    repo = AsyncMock()
    old_time = datetime.now(UTC) - timedelta(hours=25)
    user = make_user(status=UserStatus.PENDING_VERIFICATION, updated_at=old_time)
    repo.find_by_verification_token.return_value = user
    svc = make_service(repo)

    with pytest.raises(ValidationError) as exc_info:
        await svc.verify_email(VerifyEmailCommand(token="tok"))

    assert exc_info.value.error_code == "INVALID_VERIFICATION_TOKEN"


@pytest.mark.asyncio
async def test_verify_email_success_no_events() -> None:
    repo = AsyncMock()
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_verification_token.return_value = user
    svc = make_service(repo)

    await svc.verify_email(VerifyEmailCommand(token="tok"))

    repo.update.assert_called_once_with(user)
    assert user.email_verified is True
    assert user.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_verify_email_success_with_events() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_verification_token.return_value = user
    svc = make_service(repo, events=events)

    await svc.verify_email(VerifyEmailCommand(token="tok"))

    events.publish.assert_called_once()
    call_kwargs = events.publish.call_args
    assert call_kwargs.kwargs["detail_type"] == "identity.user.activated"


# ─── resend_verification ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resend_verification_user_not_found_silent() -> None:
    repo = AsyncMock()
    repo.find_by_email.return_value = None
    svc = make_service(repo)

    # Should complete without error
    await svc.resend_verification(ResendVerificationCommand(email="ghost@example.com"))
    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_resend_verification_user_already_active_no_action() -> None:
    repo = AsyncMock()
    user = make_user(status=UserStatus.ACTIVE)
    repo.find_by_email.return_value = user
    svc = make_service(repo)

    await svc.resend_verification(ResendVerificationCommand(email="user@example.com"))
    repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_resend_verification_pending_generates_token() -> None:
    repo = AsyncMock()
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_email.return_value = user
    svc = make_service(repo)

    await svc.resend_verification(ResendVerificationCommand(email="user@example.com"))

    repo.update.assert_called_once_with(user)
    assert user.email_verification_token is not None


@pytest.mark.asyncio
async def test_resend_verification_pending_with_events() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    user = make_user(status=UserStatus.PENDING_VERIFICATION)
    repo.find_by_email.return_value = user
    svc = make_service(repo, events=events)

    await svc.resend_verification(ResendVerificationCommand(email="user@example.com"))

    events.publish.assert_called_once()
    call_kwargs = events.publish.call_args
    assert call_kwargs.kwargs["detail_type"] == "identity.auth.verification_requested"


# ─── logout ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_invalid_token_raises_auth_error() -> None:
    repo = AsyncMock()
    token_svc = MagicMock()
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = make_service(repo, token_svc=token_svc)

    with pytest.raises(AuthenticationError) as exc_info:
        await svc.logout(LogoutCommand(access_token="bad"))

    assert exc_info.value.error_code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_logout_missing_jti_raises_auth_error() -> None:
    repo = AsyncMock()
    token_svc = MagicMock()
    token_svc.verify_token.return_value = {"sub": "user-id", "exp": 9999999999}
    # No "jti" key → jti will be empty string
    svc = make_service(repo, token_svc=token_svc)

    with pytest.raises(AuthenticationError) as exc_info:
        await svc.logout(LogoutCommand(access_token="tok"))

    assert exc_info.value.error_code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_logout_success_blacklists_jti() -> None:
    repo = AsyncMock()
    blacklist = AsyncMock()
    token_svc = MagicMock()
    token_svc.verify_token.return_value = {
        "jti": "some-jti",
        "exp": 9999999999,
    }  # gitguardian:ignore
    svc = make_service(repo, token_svc=token_svc, blacklist=blacklist)

    await svc.logout(LogoutCommand(access_token="valid-tok"))  # gitguardian:ignore

    blacklist.add.assert_called_once_with("some-jti", 9999999999)


# ─── authenticate event publishing branches ───────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_wrong_password_publishes_login_failed_event() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    hasher = MagicMock()
    hasher.verify.return_value = False
    user = make_user(status=UserStatus.ACTIVE)
    repo.find_by_email.return_value = user
    svc = make_service(repo, hasher=hasher, events=events)

    with pytest.raises(AuthenticationError):
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="wrong"))

    events.publish.assert_called()
    published_types = [c.kwargs["detail_type"] for c in events.publish.call_args_list]
    assert "identity.auth.login_failed" in published_types


@pytest.mark.asyncio
async def test_authenticate_fifth_failure_publishes_account_locked_event() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    hasher = MagicMock()
    hasher.verify.return_value = False
    user = make_user(status=UserStatus.ACTIVE)
    # Set to 4 failed attempts so the 5th triggers lockout
    user.failed_login_attempts = 4
    repo.find_by_email.return_value = user
    svc = make_service(repo, hasher=hasher, events=events)

    with pytest.raises(AccountLockedError) as exc_info:
        await svc.authenticate(AuthenticateCommand(email="user@example.com", password="wrong"))

    assert exc_info.value.error_code == "ACCOUNT_LOCKED"
    assert "retry_after_seconds" in exc_info.value.additional_data
    assert "locked" in exc_info.value.user_message.lower()
    published_types = [c.kwargs["detail_type"] for c in events.publish.call_args_list]
    assert "identity.auth.login_failed" in published_types
    assert "identity.auth.account_locked" in published_types


@pytest.mark.asyncio
async def test_authenticate_success_publishes_login_success_event() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    token_svc = MagicMock()
    token_svc.create_access_token.return_value = "access"
    token_svc.create_refresh_token.return_value = "refresh"
    user = make_user(status=UserStatus.ACTIVE)
    repo.find_by_email.return_value = user
    svc = make_service(repo, token_svc=token_svc, events=events)

    result = await svc.authenticate(AuthenticateCommand(email="user@example.com", password="pw"))

    assert result.access_token == "access"
    events.publish.assert_called_once()
    assert events.publish.call_args.kwargs["detail_type"] == "identity.auth.login_success"


# ─── register with event_publisher ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_with_events_publishes_user_registered() -> None:
    repo = AsyncMock()
    events = AsyncMock()
    repo.find_by_email.return_value = None
    repo.save.side_effect = lambda u: u
    svc = make_service(repo, events=events)

    cmd = RegisterUserCommand(
        email="new@example.com", password="Str0ng!Pass", full_name="New User"
    )  # gitguardian:ignore
    await svc.register(cmd)

    events.publish.assert_called_once()
    call_kwargs = events.publish.call_args.kwargs
    assert call_kwargs["detail_type"] == "identity.user.registered"
    assert call_kwargs["payload"]["email"] == "new@example.com"
