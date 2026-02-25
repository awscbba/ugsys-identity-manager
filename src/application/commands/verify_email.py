"""Verify email command DTO."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifyEmailCommand:
    """Command to verify a user's email address."""

    token: str
