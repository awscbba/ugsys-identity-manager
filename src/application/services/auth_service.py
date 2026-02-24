"""Auth application service — orchestrates register + authenticate + refresh use cases."""

from typing import Protocol

import structlog

from src.application.commands.authenticate_user import AuthenticateCommand, TokenPair
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.commands.register_user import RegisterUserCommand
from src.application.commands.reset_password import ForgotPasswordCommand, ResetPasswordCommand
from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
from src.domain.entities.user import User
from src.domain.repositories.token_service import TokenService
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class EventPublisherProtocol(Protocol):
    def publish(self, source: str, detail_type: str, detail: dict) -> None: ...  # type: ignore[type-arg]


# Service accounts — in prod these come from Secrets Manager / env vars.
# Keyed by client_id → {"secret": str, "roles": list[str]}
ServiceAccountsMap = dict[str, dict[str, object]]


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        token_service: TokenService,
        password_hasher: PasswordHasher,
        event_publisher: EventPublisherProtocol | None = None,
        service_accounts: ServiceAccountsMap | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._events = event_publisher
        self._service_accounts: ServiceAccountsMap = service_accounts or {}

    async def register(self, command: RegisterUserCommand) -> User:
        logger.info("auth_service.register.started", email=command.email)
        existing = await self._user_repo.find_by_email(command.email)
        if existing:
            logger.warning("auth_service.register.duplicate", email=command.email)
            raise ValueError(f"Email already registered: {command.email}")
        hashed = self._password_hasher.hash(command.password)
        user = User(
            email=command.email,
            hashed_password=hashed,
            full_name=command.full_name,
        )
        saved = await self._user_repo.save(user)
        logger.info("auth_service.register.completed", user_id=str(saved.id))
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.user.created",
                detail={"user_id": str(saved.id), "email": saved.email},
            )
        return saved

    async def authenticate(self, command: AuthenticateCommand) -> TokenPair:
        logger.info("auth_service.authenticate.started")
        user = await self._user_repo.find_by_email(command.email)
        if not user or not self._password_hasher.verify(command.password, user.hashed_password):
            logger.warning("auth_service.authenticate.invalid_credentials")
            if self._events and user:
                self._events.publish(
                    source="ugsys.identity-manager",
                    detail_type="identity.auth.login_failed",
                    detail={"user_id": str(user.id)},
                )
            raise ValueError("Invalid credentials")
        if not user.is_active():
            logger.warning("auth_service.authenticate.inactive", user_id=str(user.id))
            raise ValueError("Account is not active")
        access_token = self._token_service.create_access_token(
            user_id=user.id,
            roles=[r.value for r in user.roles],
        )
        refresh_token = self._token_service.create_refresh_token(user_id=user.id)
        logger.info("auth_service.authenticate.completed", user_id=str(user.id))
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.auth.login_success",
                detail={"user_id": str(user.id)},
            )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, command: RefreshTokenCommand) -> TokenPair:
        logger.info("auth_service.refresh.started")
        try:
            payload = self._token_service.verify_token(command.refresh_token)
        except ValueError as e:
            logger.warning("auth_service.refresh.invalid_token", error=str(e))
            raise ValueError("Invalid or expired refresh token") from e

        if payload.get("type") != "refresh":
            raise ValueError("Token is not a refresh token")

        from uuid import UUID

        user_id = UUID(str(payload["sub"]))
        user = await self._user_repo.find_by_id(user_id)
        if not user or not user.is_active():
            raise ValueError("User not found or inactive")

        access_token = self._token_service.create_access_token(
            user_id=user.id,
            roles=[r.value for r in user.roles],
        )
        new_refresh = self._token_service.create_refresh_token(user_id=user.id)
        logger.info("auth_service.refresh.completed", user_id=str(user.id))
        return TokenPair(access_token=access_token, refresh_token=new_refresh)

    async def forgot_password(self, command: ForgotPasswordCommand) -> str | None:
        """Generate a password-reset token. Returns token (or None if email not found).

        We always return 200 to the caller to avoid user enumeration — the token
        is returned here so the caller (router / omnichannel service) can send the email.
        """
        logger.info("auth_service.forgot_password.started")
        user = await self._user_repo.find_by_email(command.email)
        if not user:
            logger.info("auth_service.forgot_password.not_found")
            return None
        token = self._token_service.create_password_reset_token(user_id=user.id, email=user.email)
        logger.info("auth_service.forgot_password.token_created", user_id=str(user.id))
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.auth.password_reset_requested",
                detail={"user_id": str(user.id), "email": user.email, "reset_token": token},
            )
        return token

    async def reset_password(self, command: ResetPasswordCommand) -> None:
        """Validate reset token and update the user's password."""
        logger.info("auth_service.reset_password.started")
        try:
            payload = self._token_service.verify_token(command.token)
        except ValueError as e:
            logger.warning("auth_service.reset_password.invalid_token", error=str(e))
            raise ValueError("Invalid or expired reset token") from e

        if payload.get("type") != "password_reset":
            raise ValueError("Invalid token type")

        from uuid import UUID

        user_id = UUID(str(payload["sub"]))
        user = await self._user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        user.hashed_password = self._password_hasher.hash(command.new_password)
        user.activate()  # auto-activate on successful reset (covers pending_verification)
        await self._user_repo.update(user)
        logger.info("auth_service.reset_password.completed", user_id=str(user.id))

    def validate_token(self, command: ValidateTokenCommand) -> dict[str, object]:
        """Introspect a token — used by other services for S2S validation."""
        logger.info("auth_service.validate_token.started")
        try:
            payload = self._token_service.verify_token(command.token)
        except ValueError as e:
            logger.warning("auth_service.validate_token.invalid", error=str(e))
            raise ValueError("Invalid or expired token") from e
        logger.info("auth_service.validate_token.valid", sub=str(payload.get("sub")))
        return payload

    def issue_service_token(self, command: ServiceTokenCommand) -> TokenPair:
        """client_credentials grant — issues a service access token."""
        logger.info("auth_service.service_token.started", client_id=command.client_id)
        account = self._service_accounts.get(command.client_id)
        if not account:
            logger.warning("auth_service.service_token.unknown_client", client_id=command.client_id)
            raise ValueError("Invalid client credentials")
        stored_secret = str(account.get("secret", ""))
        if not self._password_hasher.verify(command.client_secret, stored_secret):
            logger.warning("auth_service.service_token.bad_secret", client_id=command.client_id)
            raise ValueError("Invalid client credentials")
        roles: list[str] = [str(r) for r in list(account.get("roles", []))]  # type: ignore[arg-type]
        token = self._token_service.create_service_token(client_id=command.client_id, roles=roles)
        logger.info("auth_service.service_token.issued", client_id=command.client_id)
        # Service tokens don't have a refresh token
        return TokenPair(access_token=token, refresh_token="")
