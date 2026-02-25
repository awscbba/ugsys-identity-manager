"""Service token commands (client_credentials grant)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceTokenCommand:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class ValidateTokenCommand:
    token: str
