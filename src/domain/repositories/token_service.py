"""Token service port (interface)."""

from abc import ABC, abstractmethod
from uuid import UUID


class TokenService(ABC):
    """Token service port. All tokens MUST include a unique `jti` claim.

    verify_token MUST check the token blacklist before returning the payload.
    """

    @abstractmethod
    def create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str: ...

    @abstractmethod
    def create_refresh_token(self, user_id: UUID) -> str: ...

    @abstractmethod
    def create_password_reset_token(self, user_id: UUID, email: str) -> str: ...

    @abstractmethod
    def create_service_token(self, client_id: str, roles: list[str]) -> str: ...

    @abstractmethod
    def verify_token(self, token: str) -> dict[str, object]:
        """Verify token signature, expiry, and blacklist status.

        Raises AuthenticationError if token is invalid, expired, or blacklisted.
        All tokens contain a `jti` (JWT ID) claim — a unique UUID4 per token.
        """
        ...
