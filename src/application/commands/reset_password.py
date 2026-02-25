"""Password reset commands."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ForgotPasswordCommand:
    email: str


@dataclass(frozen=True)
class ResetPasswordCommand:
    token: str
    new_password: str
