"""Register user command (write DTO)."""

from dataclasses import dataclass


@dataclass
class RegisterUserCommand:
    email: str
    password: str
    full_name: str
