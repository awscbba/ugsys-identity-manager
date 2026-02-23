"""Register user use case."""

from dataclasses import dataclass
from typing import Protocol

from src.domain.entities.user import User
from src.domain.ports.user_repository import UserRepository


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...


@dataclass
class RegisterUserCommand:
    email: str
    password: str
    full_name: str


class RegisterUserUseCase:
    def __init__(self, user_repo: UserRepository, password_hasher: PasswordHasher) -> None:
        self._user_repo = user_repo
        self._password_hasher = password_hasher

    async def execute(self, command: RegisterUserCommand) -> User:
        existing = await self._user_repo.find_by_email(command.email)
        if existing:
            raise ValueError(f"Email already registered: {command.email}")

        hashed = self._password_hasher.hash(command.password)
        user = User(
            email=command.email,
            hashed_password=hashed,
            full_name=command.full_name,
        )
        return await self._user_repo.save(user)
