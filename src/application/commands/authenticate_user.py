"""Authenticate user command (write DTO)."""

from dataclasses import dataclass


@dataclass
class AuthenticateCommand:
    email: str
    password: str


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    require_password_change: bool = False
