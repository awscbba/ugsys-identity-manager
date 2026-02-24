"""Token service port (interface)."""

from abc import ABC, abstractmethod
from uuid import UUID


class TokenService(ABC):
    @abstractmethod
    def create_access_token(self, user_id: UUID, roles: list[str]) -> str: ...

    @abstractmethod
    def create_refresh_token(self, user_id: UUID) -> str: ...

    @abstractmethod
    def create_password_reset_token(self, user_id: UUID, email: str) -> str: ...

    @abstractmethod
    def create_service_token(self, client_id: str, roles: list[str]) -> str: ...

    @abstractmethod
    def verify_token(self, token: str) -> dict[str, object]: ...
