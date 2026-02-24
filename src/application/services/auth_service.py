"""Auth application service — orchestrates register + authenticate + refresh use cases."""

from typing import Protocol

import structlog

from src.application.commands.authenticate_user import AuthenticateCommand, TokenPair
from src.application.commands.refresh_token import RefreshTokenCommand
from src.application.commands.register_user import RegisterUserCommand
from src.domain.entities.user import User
from src.domain.repositories.token_service import TokenService
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class EventPublisherProtocol(Protocol):
    def publish(self, source: str, detail_type: str, detail: dict) -> None: ...  # type: ignore[type-arg]


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        token_service: TokenService,
        password_hasher: PasswordHasher,
        event_publisher: EventPublisherProtocol | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._events = event_publisher

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
