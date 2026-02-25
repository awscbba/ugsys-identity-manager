"""Token blacklist repository port (interface)."""

from abc import ABC, abstractmethod


class TokenBlacklistRepository(ABC):
    """Port for token revocation storage."""

    @abstractmethod
    async def add(self, jti: str, ttl_epoch: int) -> None:
        """Store a revoked token JTI with TTL for auto-expiry."""
        ...

    @abstractmethod
    async def is_blacklisted(self, jti: str) -> bool:
        """Check if a token JTI has been revoked."""
        ...
