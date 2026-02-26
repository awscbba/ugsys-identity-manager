"""Auth request/response DTOs — extracted from presentation layer.

These live in the application layer so they can be referenced by
IAuthService and tested independently of FastAPI.
"""

from __future__ import annotations

import html

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("full_name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return html.escape(v.strip())


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ValidateTokenRequest(BaseModel):
    token: str


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ServiceTokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int = 3600


# Alias — tasks.md spec uses RegisterUserRequest; router uses RegisterRequest
RegisterUserRequest = RegisterRequest
