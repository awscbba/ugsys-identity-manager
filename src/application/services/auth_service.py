"""Auth application service — orchestrates register + authenticate + refresh use cases."""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import structlog

from src.application.commands.authenticate_user import AuthenticateCommand, TokenPair
from src.application.commands.logout import LogoutCommand
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.resend_verification import ResendVerificationCommand
from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
from src.application.commands.verify_email import VerifyEmailCommand
from src.application.interfaces.auth_service import IAuthService
from src.domain.entities.outbox_event import OutboxEvent
from src.domain.entities.user import User, UserStatus
from src.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.domain.repositories.event_publisher import EventPublisher
from src.domain.repositories.outbox_repository import OutboxRepository
from src.domain.repositories.token_blacklist_repository import TokenBlacklistRepository
from src.domain.repositories.token_service import TokenService
from src.domain.repositories.unit_of_work import UnitOfWork
from src.domain.repositories.user_repository import UserRepository
from src.domain.value_objects.password_validator import PasswordValidator

logger = structlog.get_logger()


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


# Service accounts — in prod these come from Secrets Manager / env vars.
# Keyed by client_id → {"secret": str, "roles": list[str]}
ServiceAccountsMap = dict[str, dict[str, object]]


class AuthService(IAuthService):
    def __init__(
        self,
        user_repo: UserRepository,
        token_service: TokenService,
        password_hasher: PasswordHasher,
        token_blacklist: TokenBlacklistRepository,
        password_validator: PasswordValidator,
        event_publisher: EventPublisher | None = None,
        service_accounts: ServiceAccountsMap | None = None,
        outbox_repo: OutboxRepository | None = None,
        unit_of_work: UnitOfWork | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._token_blacklist = token_blacklist
        self._password_validator = password_validator
        self._events = event_publisher
        self._service_accounts: ServiceAccountsMap = service_accounts or {}
        self._outbox_repo = outbox_repo
        self._unit_of_work = unit_of_work

    async def register(self, command: RegisterUserCommand) -> User:
        logger.info("auth_service.register.started", email=command.email)
        start = time.perf_counter()

        # Validate password strength
        violations = self._password_validator.validate(command.password)
        if violations:
            raise ValidationError(
                message=f"Password validation failed: {violations}",
                user_message="Password does not meet requirements",
                error_code="WEAK_PASSWORD",
                additional_data={"violations": violations},
            )

        existing = await self._user_repo.find_by_email(command.email)
        if existing:
            logger.warning("auth_service.register.duplicate", email=command.email)
            raise ConflictError(
                message=f"Email already registered: {command.email}",
                user_message="This email address is already in use",
                error_code="EMAIL_ALREADY_EXISTS",
            )

        hashed = self._password_hasher.hash(command.password)
        user = User(
            email=command.email,
            hashed_password=hashed,
            full_name=command.full_name,
            status=UserStatus.PENDING_VERIFICATION,
        )
        verification_token = user.generate_verification_token()

        if self._outbox_repo and self._unit_of_work:
            # Atomic dual-write: user save + outbox event in one transaction
            expires_at = datetime.now(UTC) + timedelta(hours=24)
            outbox_event = OutboxEvent(
                id=str(uuid4()),
                aggregate_type="User",
                aggregate_id=str(user.id),
                event_type="identity.user.registered",
                payload=json.dumps(
                    {
                        "user_id": str(user.id),
                        "email": user.email,
                        "full_name": user.full_name,
                        "verification_token": verification_token,
                        "expires_at": expires_at.isoformat(),
                    }
                ),
                created_at=datetime.now(UTC).isoformat(),
                status="pending",
            )
            await self._unit_of_work.execute(
                [
                    self._user_repo.save_operation(user),
                    self._outbox_repo.save_operation(outbox_event),
                ]
            )
            saved = user
        else:
            # Fallback: direct save + log-and-continue publish
            saved = await self._user_repo.save(user)
            if self._events:
                expires_at = datetime.now(UTC) + timedelta(hours=24)
                await self._events.publish(
                    detail_type="identity.user.registered",
                    payload={
                        "user_id": str(saved.id),
                        "email": saved.email,
                        "full_name": saved.full_name,
                        "verification_token": verification_token,
                        "expires_at": expires_at.isoformat(),
                    },
                )

        logger.info(
            "auth_service.register.completed",
            user_id=str(saved.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return saved

    async def authenticate(self, command: AuthenticateCommand) -> TokenPair:
        logger.info("auth_service.authenticate.started")
        start = time.perf_counter()

        # 1. Find user by email
        user = await self._user_repo.find_by_email(command.email)

        # 2. User not found
        if not user:
            logger.warning("auth_service.authenticate.invalid_credentials")
            raise AuthenticationError(
                message="Login attempt for non-existent email",
                user_message="Invalid credentials",
                error_code="INVALID_CREDENTIALS",
            )

        # 3. Check account lockout BEFORE password verification
        if user.is_locked():
            retry_after = int(
                (user.account_locked_until - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
            )
            retry_after = max(retry_after, 0)
            logger.warning(
                "auth_service.authenticate.account_locked",
                user_id=str(user.id),
                retry_after_seconds=retry_after,
            )
            raise AccountLockedError(
                message=f"Account {user.id} is locked until {user.account_locked_until}",
                user_message="Account is temporarily locked due to too many failed login attempts",
                error_code="ACCOUNT_LOCKED",
                additional_data={"retry_after_seconds": retry_after},
            )

        # 4. Verify password
        if not self._password_hasher.verify(command.password, user.hashed_password):
            user.record_failed_login()
            await self._user_repo.update(user)

            if self._events:
                await self._events.publish(
                    detail_type="identity.auth.login_failed",
                    payload={
                        "email": user.email,
                        "ip_address": "",
                        "attempt_count": user.failed_login_attempts,
                    },
                )
                # On 5th failure (account now locked), also publish account_locked
                if user.failed_login_attempts >= 5:
                    await self._events.publish(
                        detail_type="identity.auth.account_locked",
                        payload={
                            "user_id": str(user.id),
                            "email": user.email,
                            "locked_until": user.account_locked_until.isoformat()
                            if user.account_locked_until
                            else None,
                        },
                    )

            # If the account just got locked on this attempt, return 423 immediately
            if user.is_locked():
                retry_after = int(
                    (user.account_locked_until - datetime.now(UTC)).total_seconds()  # type: ignore[operator]
                )
                retry_after = max(retry_after, 0)
                logger.warning(
                    "auth_service.authenticate.account_locked",
                    user_id=str(user.id),
                    retry_after_seconds=retry_after,
                )
                raise AccountLockedError(
                    message=(
                        f"Account {user.id} locked after 5 failed attempts"
                        f" until {user.account_locked_until}"
                    ),
                    user_message=(
                        "Account is temporarily locked due to too many failed login attempts"
                    ),
                    error_code="ACCOUNT_LOCKED",
                    additional_data={"retry_after_seconds": retry_after},
                )

            logger.warning(
                "auth_service.authenticate.invalid_credentials",
                user_id=str(user.id),
                attempt_count=user.failed_login_attempts,
            )
            raise AuthenticationError(
                message=f"Invalid password for user {user.id}",
                user_message="Invalid credentials",
                error_code="INVALID_CREDENTIALS",
            )

        # 5. Check pending_verification status
        if user.status == UserStatus.PENDING_VERIFICATION:
            logger.warning(
                "auth_service.authenticate.email_not_verified",
                user_id=str(user.id),
            )
            raise AuthenticationError(
                message=f"User {user.id} has not verified their email",
                user_message="Email verification is required before login",
                error_code="EMAIL_NOT_VERIFIED",
            )

        # 6. Check require_password_change flag
        if user.require_password_change:
            logger.warning(
                "auth_service.authenticate.password_change_required",
                user_id=str(user.id),
            )
            raise AuthenticationError(
                message=f"User {user.id} must change their password",
                user_message="Password change is required before login",
                error_code="PASSWORD_CHANGE_REQUIRED",
            )

        # 7. Record successful login, persist, publish
        user.record_successful_login()
        await self._user_repo.update(user)

        if self._events:
            await self._events.publish(
                detail_type="identity.auth.login_success",
                payload={"user_id": str(user.id), "ip_address": ""},
            )

        # 8. Create tokens and return
        access_token = self._token_service.create_access_token(
            user_id=user.id,
            roles=[r.value for r in user.roles],
        )
        refresh_token = self._token_service.create_refresh_token(user_id=user.id)
        logger.info(
            "auth_service.authenticate.completed",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            require_password_change=user.require_password_change,
        )

    async def refresh(self, command: RefreshTokenCommand) -> TokenPair:
        logger.info("auth_service.refresh.started")
        start = time.perf_counter()
        try:
            payload = self._token_service.verify_token(command.refresh_token)
        except (ValueError, AuthenticationError) as e:
            logger.warning("auth_service.refresh.invalid_token", error=str(e))
            raise AuthenticationError(
                message=f"Invalid refresh token: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        if payload.get("type") != "refresh":
            raise AuthenticationError(
                message=f"Token type is '{payload.get('type')}', expected 'refresh'",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        from uuid import UUID

        user_id = UUID(str(payload["sub"]))
        user = await self._user_repo.find_by_id(user_id)
        if not user or not user.is_active():
            raise AuthenticationError(
                message=f"User {user_id} not found or inactive during refresh",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        access_token = self._token_service.create_access_token(
            user_id=user.id,
            roles=[r.value for r in user.roles],
        )
        new_refresh = self._token_service.create_refresh_token(user_id=user.id)
        logger.info(
            "auth_service.refresh.completed",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return TokenPair(access_token=access_token, refresh_token=new_refresh)

    async def forgot_password(self, command: ForgotPasswordCommand) -> str | None:
        """Generate a password-reset token. Returns token (or None if email not found).

        We always return 200 to the caller to avoid user enumeration — the token
        is returned here so the caller (router / omnichannel service) can send the email.
        """
        logger.info("auth_service.forgot_password.started")
        start = time.perf_counter()
        user = await self._user_repo.find_by_email(command.email)
        if not user:
            logger.info("auth_service.forgot_password.not_found")
            return None
        token = self._token_service.create_password_reset_token(user_id=user.id, email=user.email)
        # Generate an opaque token_id — never store the raw JWT in the outbox/event payload
        token_id = str(uuid4())
        logger.info(
            "auth_service.forgot_password.token_created",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        if self._events:
            await self._events.publish(
                detail_type="identity.auth.password_reset_requested",
                payload={
                    "user_id": str(user.id),
                    "email": user.email,
                    "token_id": token_id,
                },
            )
        return token

    async def reset_password(self, command: ResetPasswordCommand) -> None:
        """Validate reset token and update the user's password."""
        logger.info("auth_service.reset_password.started")
        start = time.perf_counter()
        try:
            payload = self._token_service.verify_token(command.token)
        except (ValueError, AuthenticationError) as e:
            logger.warning("auth_service.reset_password.invalid_token", error=str(e))
            raise AuthenticationError(
                message=f"Invalid reset token: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        if payload.get("type") != "password_reset":
            raise AuthenticationError(
                message=f"Token type is '{payload.get('type')}', expected 'password_reset'",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        from uuid import UUID

        user_id = UUID(str(payload["sub"]))
        user = await self._user_repo.find_by_id(user_id)
        if not user:
            raise NotFoundError(
                message=f"User {user_id} not found during password reset",
                user_message="Resource not found",
                error_code="NOT_FOUND",
            )

        # Validate new password strength
        violations = self._password_validator.validate(command.new_password)
        if violations:
            raise ValidationError(
                message=f"Password validation failed: {violations}",
                user_message="Password does not meet requirements",
                error_code="WEAK_PASSWORD",
                additional_data={"violations": violations},
            )

        user.hashed_password = self._password_hasher.hash(command.new_password)
        user.require_password_change = False
        user.last_password_change = datetime.now(UTC)
        user.activate()  # auto-activate on successful reset (covers pending_verification)

        if self._outbox_repo and self._unit_of_work:
            # Atomic dual-write: user update + outbox event in one transaction
            outbox_event = OutboxEvent(
                id=str(uuid4()),
                aggregate_type="User",
                aggregate_id=str(user.id),
                event_type="identity.auth.password_changed",
                payload=json.dumps({"user_id": str(user.id), "email": user.email}),
                created_at=datetime.now(UTC).isoformat(),
                status="pending",
            )
            await self._unit_of_work.execute(
                [
                    self._user_repo.update_operation(user),
                    self._outbox_repo.save_operation(outbox_event),
                ]
            )
        else:
            await self._user_repo.update(user)
            if self._events:
                await self._events.publish(
                    detail_type="identity.auth.password_changed",
                    payload={"user_id": str(user.id), "email": user.email},
                )

        logger.info(
            "auth_service.reset_password.completed",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def validate_token(self, command: ValidateTokenCommand) -> dict[str, object]:
        """Introspect a token — used by other services for S2S validation.

        Returns {valid: true, sub, roles, type} on success,
        or {valid: false} on invalid/expired token (never raises).
        """
        logger.info("auth_service.validate_token.started")
        try:
            payload = self._token_service.verify_token(command.token)
        except (ValueError, AuthenticationError) as e:
            logger.warning("auth_service.validate_token.invalid", error=str(e))
            return {"valid": False}
        logger.info("auth_service.validate_token.valid", sub=str(payload.get("sub")))
        raw_roles = payload.get("roles")
        roles_list: list[str] = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []
        return {
            "valid": True,
            "sub": str(payload.get("sub")),
            "roles": roles_list,
            "type": str(payload.get("type")),
        }

    def issue_service_token(self, command: ServiceTokenCommand) -> TokenPair:
        """client_credentials grant — issues a service access token."""
        logger.info("auth_service.service_token.started", client_id=command.client_id)
        account = self._service_accounts.get(command.client_id)
        if not account:
            logger.warning("auth_service.service_token.unknown_client", client_id=command.client_id)
            raise AuthenticationError(
                message=f"Unknown service client: {command.client_id}",
                user_message="Invalid client credentials",
                error_code="INVALID_CLIENT_CREDENTIALS",
            )
        stored_secret = str(account.get("secret", ""))
        if not self._password_hasher.verify(command.client_secret, stored_secret):
            logger.warning("auth_service.service_token.bad_secret", client_id=command.client_id)
            raise AuthenticationError(
                message=f"Bad secret for service client: {command.client_id}",
                user_message="Invalid client credentials",
                error_code="INVALID_CLIENT_CREDENTIALS",
            )
        raw_account_roles = account.get("roles")
        roles: list[str] = (
            [str(r) for r in raw_account_roles] if isinstance(raw_account_roles, list) else []
        )
        token = self._token_service.create_service_token(client_id=command.client_id, roles=roles)
        logger.info("auth_service.service_token.issued", client_id=command.client_id)
        # Service tokens don't have a refresh token
        return TokenPair(access_token=token, refresh_token="")

    async def verify_email(self, command: VerifyEmailCommand) -> None:
        """Verify a user's email using the verification token."""
        logger.info("auth_service.verify_email.started")
        start = time.perf_counter()

        user = await self._user_repo.find_by_verification_token(command.token)
        if user is None:
            logger.warning("auth_service.verify_email.invalid_token")
            raise ValidationError(
                message=f"Verification token not found: {command.token}",
                user_message="Invalid or expired verification token",
                error_code="INVALID_VERIFICATION_TOKEN",
            )

        # Check if already verified
        if user.email_verified or user.status == UserStatus.ACTIVE:
            logger.warning(
                "auth_service.verify_email.already_verified",
                user_id=str(user.id),
            )
            raise ConflictError(
                message=f"User {user.id} email already verified",
                user_message="Email already verified",
                error_code="ALREADY_VERIFIED",
            )

        # Check token expiry (24h from updated_at as proxy)
        token_age = datetime.now(UTC) - user.updated_at
        if token_age > timedelta(hours=24):
            logger.warning(
                "auth_service.verify_email.token_expired",
                user_id=str(user.id),
            )
            raise ValidationError(
                message=f"Verification token expired for user {user.id}",
                user_message="Invalid or expired verification token",
                error_code="INVALID_VERIFICATION_TOKEN",
            )

        user.verify_email()
        await self._user_repo.update(user)

        logger.info(
            "auth_service.verify_email.completed",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )

        if self._events:
            await self._events.publish(
                detail_type="identity.user.activated",
                payload={"user_id": str(user.id), "email": user.email},
            )

    async def resend_verification(self, command: ResendVerificationCommand) -> None:
        """Resend email verification. Always returns success to prevent user enumeration."""
        logger.info("auth_service.resend_verification.started")
        start = time.perf_counter()

        user = await self._user_repo.find_by_email(command.email)

        if user and user.status == UserStatus.PENDING_VERIFICATION:
            token = user.generate_verification_token()
            await self._user_repo.update(user)

            logger.info(
                "auth_service.resend_verification.token_generated",
                user_id=str(user.id),
            )

            if self._events:
                expires_at = datetime.now(UTC) + timedelta(hours=24)
                await self._events.publish(
                    detail_type="identity.auth.verification_requested",
                    payload={
                        "user_id": str(user.id),
                        "email": user.email,
                        "verification_token": token,
                        "expires_at": expires_at.isoformat(),
                    },
                )
        else:
            logger.info("auth_service.resend_verification.no_action")

        logger.info(
            "auth_service.resend_verification.completed",
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    async def logout(self, command: LogoutCommand) -> None:
        """Logout by blacklisting the access token's jti."""
        logger.info("auth_service.logout.started")
        start = time.perf_counter()

        try:
            payload = self._token_service.verify_token(command.access_token)
        except Exception as e:
            logger.warning("auth_service.logout.invalid_token", error=str(e))
            raise AuthenticationError(
                message=f"Invalid token during logout: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        jti = str(payload.get("jti", ""))
        if not jti:
            raise AuthenticationError(
                message="Token missing jti claim",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        exp_raw = payload.get("exp", 0)
        exp = int(exp_raw) if isinstance(exp_raw, (int, float, str)) else 0
        await self._token_blacklist.add(jti, exp)

        logger.info(
            "auth_service.logout.completed",
            jti=jti,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
