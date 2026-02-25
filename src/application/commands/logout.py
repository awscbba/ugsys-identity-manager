"""Logout command DTO."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LogoutCommand:
    """Command to logout and blacklist the access token."""

    access_token: str
