"""Resend verification command DTO."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResendVerificationCommand:
    """Command to resend email verification."""

    email: str
