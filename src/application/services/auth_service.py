"""Auth application service — orchestrates register + authenticate use cases."""

from typing import Protocol

import structlog

from src.application.commands.authenticate_user import AuthenticateCommand, TokenPair
from src.application.commands.register_user import RegisterUserCommand
from src.domain.entities.user import User
from src.domain.repositories.token_service import TokenService
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        token_service: TokenService,
        password_hasher: PasswordHasher,
    ) -> None:
        self._user_repo = user_repo
        self._token_service = token_service
        self._password_hasher = password_hasher

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
        return saved

    async def authenticate(self, command: AuthenticateCommand) -> TokenPair:
        logger.info("auth_service.authenticate.started")
        user = await self._user_repo.find_by_email(command.email)
        if not user or not self._password_hasher.verify(command.password, user.hashed_password):
            logger.warning("auth_service.authenticate.invalid_credentials")
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
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
