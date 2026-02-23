"""Authenticate user use case."""

from dataclasses import dataclass

from src.domain.ports.token_service import TokenService
from src.domain.ports.user_repository import UserRepository


@dataclass
class AuthenticateCommand:
    email: str
    password: str


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthenticateUserUseCase:
    def __init__(
        self,
        user_repo: UserRepository,
        token_service: TokenService,
        password_hasher,
    ) -> None:
        self._user_repo = user_repo
        self._token_service = token_service
        self._password_hasher = password_hasher

    async def execute(self, command: AuthenticateCommand) -> TokenPair:
        user = await self._user_repo.find_by_email(command.email)
        if not user or not self._password_hasher.verify(command.password, user.hashed_password):
            raise ValueError("Invalid credentials")
        if not user.is_active():
            raise ValueError("Account is not active")

        access_token = self._token_service.create_access_token(
            user_id=user.id,
            roles=[r.value for r in user.roles],
        )
        refresh_token = self._token_service.create_refresh_token(user_id=user.id)
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
