"""User repository port (interface)."""

from abc import ABC, abstractmethod
from uuid import UUID

from src.domain.entities.user import User


class UserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def find_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def find_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def list_all(self) -> list[User]: ...

    @abstractmethod
    async def delete(self, user_id: UUID) -> None: ...

    @abstractmethod
    async def list_paginated(
        self,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        role_filter: str | None = None,
    ) -> tuple[list[User], int]:
        """Return (users_page, total_count) with optional filters."""
        ...

    @abstractmethod
    async def find_by_verification_token(self, token: str) -> User | None:
        """Find a user by their email verification token."""
        ...
