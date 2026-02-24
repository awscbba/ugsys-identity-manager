"""Refresh token command (write DTO)."""

from dataclasses import dataclass


@dataclass
class RefreshTokenCommand:
    refresh_token: str
