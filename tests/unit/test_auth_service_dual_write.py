"""Unit tests for AuthService atomic dual-write paths.

TDD: RED phase — tests written before implementation.
Covers:
  - register() uses UnitOfWork.execute() with 2 ops when outbox is wired
  - register() falls back to direct save() when outbox not wired
  - reset_password() uses UnitOfWork.execute() with 2 ops when outbox is wired
  - UnitOfWork.execute() failure propagates (no partial state)
  - forgot_password() outbox payload uses token_id, NOT raw token
  - UserService.deactivate() uses UnitOfWork.execute() with 2 ops when outbox is wired
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.commands.update_user import DeactivateUserCommand
from src.application.services.auth_service import AuthService
from src.application.services.user_service import UserService
from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import RepositoryError
from src.domain.repositories.outbox_repository import OutboxRepository
from src.domain.repositories.unit_of_work import TransactionalOperation, UnitOfWork
from src.domain.repositories.user_repository import UserRepository
from src.domain.value_objects.password_validator import PasswordValidator

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_user(status: UserStatus = UserStatus.PENDING_VERIFICATION) -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        hashed_password="hashed",
        full_name="Test User",
        status=status,
        roles=[UserRole.MEMBER],
    )


def make_save_op() -> TransactionalOperation:
    return TransactionalOperation(operation_type="Put", params={"TableName": "users", "Item": {}})


def make_outbox_op() -> TransactionalOperation:
    return TransactionalOperation(operation_type="Put", params={"TableName": "outbox", "Item": {}})


def make_auth_service(
    *,
    user_repo: AsyncMock,
    outbox_repo: AsyncMock | None = None,
    unit_of_work: AsyncMock | None = None,
    event_publisher: AsyncMock | None = None,
) -> AuthService:
    token_svc = MagicMock()
    token_svc.create_password_reset_token.return_value = "reset-jwt-token"
    token_svc.verify_token.return_value = {
        "sub": str(uuid4()),
        "type": "password_reset",
    }

    hasher = MagicMock()
    hasher.hash.return_value = "hashed_pw"
    hasher.verify.return_value = True

    token_blacklist = AsyncMock()
    password_validator = PasswordValidator()

    return AuthService(
        user_repo=user_repo,
        token_service=token_svc,
        password_hasher=hasher,
        token_blacklist=token_blacklist,
        password_validator=password_validator,
        event_publisher=event_publisher,
        outbox_repo=outbox_repo,
        unit_of_work=unit_of_work,
    )


def make_user_service(
    *,
    user_repo: AsyncMock,
    outbox_repo: AsyncMock | None = None,
    unit_of_work: AsyncMock | None = None,
    event_publisher: AsyncMock | None = None,
) -> UserService:
    return UserService(
        user_repo=user_repo,
        event_publisher=event_publisher,
        outbox_repo=outbox_repo,
        unit_of_work=unit_of_work,
    )


# ── register() — atomic dual-write ───────────────────────────────────────────


class TestRegisterAtomicDualWrite:
    """register() must use UnitOfWork.execute() with exactly 2 ops when outbox is wired."""

    @pytest.mark.asyncio
    async def test_register_calls_unit_of_work_execute(self) -> None:
        _ = make_user()
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        unit_of_work.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_passes_exactly_two_operations(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        ops = unit_of_work.execute.call_args[0][0]
        assert len(ops) == 2

    @pytest.mark.asyncio
    async def test_register_does_not_call_direct_save_when_outbox_wired(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        user_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_outbox_event_type_is_user_registered(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save_operation.return_value = make_save_op()

        captured_events: list = []

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.side_effect = lambda e: (
            captured_events.append(e) or make_outbox_op()
        )

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        assert len(captured_events) == 1
        assert captured_events[0].event_type == "identity.user.registered"


# ── register() — backward-compat fallback ────────────────────────────────────


class TestRegisterFallback:
    """When outbox/UoW not wired, register() falls back to direct save() + log-and-continue."""

    @pytest.mark.asyncio
    async def test_register_without_outbox_calls_direct_save(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save.side_effect = lambda u: u

        svc = make_auth_service(user_repo=user_repo)  # no outbox_repo, no unit_of_work
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        user_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_without_unit_of_work_calls_direct_save(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save.side_effect = lambda u: u

        outbox_repo = AsyncMock(spec=OutboxRepository)

        # outbox_repo present but unit_of_work=None → fallback
        svc = make_auth_service(user_repo=user_repo, outbox_repo=outbox_repo, unit_of_work=None)
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        user_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_fallback_publishes_event_via_event_publisher(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save.side_effect = lambda u: u

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)
        await svc.register(
            RegisterUserCommand(email="new@example.com", password="Str0ng!Pass", full_name="New")
        )

        event_publisher.publish.assert_called_once()
        call_kwargs = event_publisher.publish.call_args[1]
        assert call_kwargs["detail_type"] == "identity.user.registered"


# ── reset_password() — atomic dual-write ─────────────────────────────────────


class TestResetPasswordAtomicDualWrite:
    """reset_password() must use UnitOfWork.execute() with exactly 2 ops when outbox is wired."""

    @pytest.mark.asyncio
    async def test_reset_password_calls_unit_of_work_execute(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        # Patch token_service to return valid payload with user's id
        svc._token_service.verify_token.return_value = {
            "sub": str(user.id),
            "type": "password_reset",
        }

        await svc.reset_password(
            ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
        )

        unit_of_work.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_password_passes_exactly_two_operations(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        svc._token_service.verify_token.return_value = {
            "sub": str(user.id),
            "type": "password_reset",
        }

        await svc.reset_password(
            ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
        )

        ops = unit_of_work.execute.call_args[0][0]
        assert len(ops) == 2

    @pytest.mark.asyncio
    async def test_reset_password_does_not_call_direct_update_when_outbox_wired(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        svc._token_service.verify_token.return_value = {
            "sub": str(user.id),
            "type": "password_reset",
        }

        await svc.reset_password(
            ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
        )

        user_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_password_outbox_event_type_is_password_changed(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        captured_events: list = []
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.side_effect = lambda e: (
            captured_events.append(e) or make_outbox_op()
        )

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        svc._token_service.verify_token.return_value = {
            "sub": str(user.id),
            "type": "password_reset",
        }

        await svc.reset_password(
            ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
        )

        assert len(captured_events) == 1
        assert captured_events[0].event_type == "identity.auth.password_changed"


# ── UnitOfWork failure propagation ────────────────────────────────────────────


class TestUnitOfWorkFailurePropagation:
    """RepositoryError from UnitOfWork.execute() must propagate to caller."""

    @pytest.mark.asyncio
    async def test_register_propagates_repository_error_from_unit_of_work(self) -> None:
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = None
        user_repo.save_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.side_effect = RepositoryError(
            message="DynamoDB transaction failed",
            user_message="An unexpected error occurred",
        )

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )

        with pytest.raises(RepositoryError):
            await svc.register(
                RegisterUserCommand(
                    email="new@example.com", password="Str0ng!Pass", full_name="New"
                )
            )

    @pytest.mark.asyncio
    async def test_reset_password_propagates_repository_error_from_unit_of_work(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.side_effect = RepositoryError(
            message="DynamoDB transaction failed",
            user_message="An unexpected error occurred",
        )

        svc = make_auth_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        svc._token_service.verify_token.return_value = {
            "sub": str(user.id),
            "type": "password_reset",
        }

        with pytest.raises(RepositoryError):
            await svc.reset_password(
                ResetPasswordCommand(token="valid-token", new_password="Str0ng!Pass")
            )


# ── forgot_password() — token_id security ────────────────────────────────────


class TestForgotPasswordTokenSecurity:
    """forgot_password() must store token_id, NOT the raw token string (Req 8.1, 8.2)."""

    @pytest.mark.asyncio
    async def test_forgot_password_event_payload_contains_token_id(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = user

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)
        svc._token_service.create_password_reset_token.return_value = "raw-jwt-token-value"

        await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))

        event_publisher.publish.assert_called_once()
        payload = event_publisher.publish.call_args[1]["payload"]
        assert "token_id" in payload

    @pytest.mark.asyncio
    async def test_forgot_password_event_payload_does_not_contain_reset_token(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = user

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)
        svc._token_service.create_password_reset_token.return_value = "raw-jwt-token-value"

        await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))

        payload = event_publisher.publish.call_args[1]["payload"]
        assert "reset_token" not in payload, "Raw token must NOT be in outbox payload"

    @pytest.mark.asyncio
    async def test_forgot_password_event_payload_does_not_contain_verification_token(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = user

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)
        svc._token_service.create_password_reset_token.return_value = "raw-jwt-token-value"

        await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))

        payload = event_publisher.publish.call_args[1]["payload"]
        assert "verification_token" not in payload, "verification_token must NOT be in payload"

    @pytest.mark.asyncio
    async def test_forgot_password_token_id_is_not_the_raw_token(self) -> None:
        """token_id must be an opaque identifier, not the raw JWT string."""
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = user

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)
        raw_token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEifQ.signature"
        svc._token_service.create_password_reset_token.return_value = raw_token

        await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))

        payload = event_publisher.publish.call_args[1]["payload"]
        token_id = payload.get("token_id", "")
        assert token_id != raw_token, "token_id must NOT equal the raw JWT string"

    @pytest.mark.asyncio
    async def test_forgot_password_payload_contains_user_id_and_email(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_email.return_value = user

        event_publisher = AsyncMock()
        svc = make_auth_service(user_repo=user_repo, event_publisher=event_publisher)

        await svc.forgot_password(ForgotPasswordCommand(email="user@example.com"))

        payload = event_publisher.publish.call_args[1]["payload"]
        assert "user_id" in payload
        assert "email" in payload


# ── UserService.deactivate() — atomic dual-write ──────────────────────────────


class TestDeactivateAtomicDualWrite:
    """UserService.deactivate() must use UnitOfWork.execute() with 2 ops when outbox is wired."""

    @pytest.mark.asyncio
    async def test_deactivate_calls_unit_of_work_execute(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_user_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.deactivate(DeactivateUserCommand(user_id=user.id, requester_id=str(user.id)))

        unit_of_work.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deactivate_passes_exactly_two_operations(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_user_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.deactivate(DeactivateUserCommand(user_id=user.id, requester_id=str(user.id)))

        ops = unit_of_work.execute.call_args[0][0]
        assert len(ops) == 2

    @pytest.mark.asyncio
    async def test_deactivate_does_not_call_direct_update_when_outbox_wired(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.return_value = make_outbox_op()

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_user_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.deactivate(DeactivateUserCommand(user_id=user.id, requester_id=str(user.id)))

        user_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_deactivate_outbox_event_type_is_user_deactivated(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update_operation.return_value = make_save_op()

        captured_events: list = []
        outbox_repo = AsyncMock(spec=OutboxRepository)
        outbox_repo.save_operation.side_effect = lambda e: (
            captured_events.append(e) or make_outbox_op()
        )

        unit_of_work = AsyncMock(spec=UnitOfWork)
        unit_of_work.execute.return_value = None

        svc = make_user_service(
            user_repo=user_repo,
            outbox_repo=outbox_repo,
            unit_of_work=unit_of_work,
        )
        await svc.deactivate(DeactivateUserCommand(user_id=user.id, requester_id=str(user.id)))

        assert len(captured_events) == 1
        assert captured_events[0].event_type == "identity.user.deactivated"

    @pytest.mark.asyncio
    async def test_deactivate_fallback_calls_direct_update_when_no_outbox(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user_repo = AsyncMock(spec=UserRepository)
        user_repo.find_by_id.return_value = user
        user_repo.update.return_value = user

        svc = make_user_service(user_repo=user_repo)  # no outbox, no UoW
        await svc.deactivate(DeactivateUserCommand(user_id=user.id, requester_id=str(user.id)))

        user_repo.update.assert_called_once()
