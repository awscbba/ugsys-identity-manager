"""Password strength validator — domain value object."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class PasswordValidator:
    """Validates password complexity rules. Returns list of violated rules."""

    SPECIAL_CHARS: ClassVar[str] = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    MIN_LENGTH: ClassVar[int] = 8

    @staticmethod
    def validate(password: str) -> list[str]:
        """Return list of violated rules. Empty list = valid password."""
        violations: list[str] = []

        if len(password) < PasswordValidator.MIN_LENGTH:
            violations.append(
                f"Password must be at least {PasswordValidator.MIN_LENGTH} characters"
            )
        if not any(c.isupper() for c in password):
            violations.append("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in password):
            violations.append("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in password):
            violations.append("Password must contain at least one digit")
        if not any(c in PasswordValidator.SPECIAL_CHARS for c in password):
            violations.append("Password must contain at least one special character")

        return violations
