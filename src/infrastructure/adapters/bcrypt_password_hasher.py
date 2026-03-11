"""Bcrypt password hasher — infrastructure adapter implementing the PasswordHasher Protocol."""

import bcrypt


class BcryptPasswordHasher:
    """Concrete bcrypt password hasher with configurable work factor.

    Satisfies the PasswordHasher Protocol defined in auth_service.py.
    Work factor (rounds) must be >= 12 in all environments.
    """

    def __init__(self, rounds: int = 12) -> None:
        if rounds < 12:
            raise ValueError(f"bcrypt rounds must be >= 12, got {rounds}")
        self._rounds = rounds

    def hash(self, password: str) -> str:
        """Hash a plaintext password using bcrypt with a fresh random salt."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=self._rounds)).decode(
            "utf-8"
        )

    def verify(self, plain: str, hashed: str) -> bool:
        """Verify a plaintext password against a bcrypt hash. Never raises on wrong password."""
        return bool(bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8")))
