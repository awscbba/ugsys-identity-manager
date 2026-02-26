"""Task 10.1 — DTOs are importable from src/application/dtos/ and have correct structure."""

import html

from src.application.dtos.auth_dtos import (
    ForgotPasswordRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterUserRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    ServiceTokenRequest,
    ServiceTokenResponse,
    TokenResponse,
    ValidateTokenRequest,
    VerifyEmailRequest,
)
from src.application.dtos.user_dtos import (
    AssignRoleRequest,
    PaginatedUsersResponse,
    UpdateProfileRequest,
    UserResponse,
)

# ── auth_dtos ─────────────────────────────────────────────────────────────────


def test_register_request_sanitizes_name() -> None:
    req = RegisterRequest(
        email="dev@example.com", password="Str0ng!Pass", full_name="  <b>Alice</b>  "
    )
    assert req.full_name == html.escape("<b>Alice</b>")


def test_register_request_strips_whitespace() -> None:
    req = RegisterRequest(email="dev@example.com", password="Str0ng!Pass", full_name="  Alice  ")
    assert req.full_name == "Alice"


def test_register_user_request_is_alias_for_register_request() -> None:
    assert RegisterUserRequest is RegisterRequest


def test_login_request_importable() -> None:
    from src.application.dtos.auth_dtos import LoginRequest

    req = LoginRequest(email="dev@example.com", password="secret")
    assert req.email == "dev@example.com"


def test_refresh_request_importable() -> None:
    req = RefreshRequest(refresh_token="tok")
    assert req.refresh_token == "tok"


def test_forgot_password_request_importable() -> None:
    req = ForgotPasswordRequest(email="dev@example.com")
    assert str(req.email) == "dev@example.com"


def test_reset_password_request_importable() -> None:
    req = ResetPasswordRequest(token="t", new_password="p")
    assert req.token == "t"


def test_verify_email_request_importable() -> None:
    req = VerifyEmailRequest(token="tok")
    assert req.token == "tok"


def test_resend_verification_request_importable() -> None:
    req = ResendVerificationRequest(email="dev@example.com")
    assert str(req.email) == "dev@example.com"


def test_service_token_request_importable() -> None:
    req = ServiceTokenRequest(client_id="svc", client_secret="sec")
    assert req.client_id == "svc"


def test_validate_token_request_importable() -> None:
    req = ValidateTokenRequest(token="tok")
    assert req.token == "tok"


def test_token_response_defaults() -> None:
    resp = TokenResponse(access_token="a", refresh_token="r")
    assert resp.token_type == "bearer"


def test_service_token_response_defaults() -> None:
    resp = ServiceTokenResponse(access_token="a")
    assert resp.token_type == "bearer"
    assert resp.expires_in == 3600


# ── user_dtos ─────────────────────────────────────────────────────────────────


def test_update_profile_request_importable() -> None:
    req = UpdateProfileRequest(full_name="Alice")
    assert req.full_name == "Alice"


def test_assign_role_request_importable() -> None:
    from src.domain.entities.user import UserRole

    req = AssignRoleRequest(role=UserRole.ADMIN)
    assert req.role == UserRole.ADMIN


def test_user_response_from_domain() -> None:
    from unittest.mock import MagicMock

    from src.domain.entities.user import UserRole, UserStatus

    user = MagicMock()
    user.id = "01JXXX"
    user.email = "dev@example.com"
    user.full_name = "Dev User"
    user.status = UserStatus.ACTIVE
    user.roles = [UserRole.MEMBER]

    resp = UserResponse.from_domain(user)
    assert resp.id == "01JXXX"
    assert resp.email == "dev@example.com"
    assert resp.full_name == "Dev User"
    assert resp.status == "active"
    assert resp.roles == ["member"]


def test_paginated_users_response_importable() -> None:
    resp = PaginatedUsersResponse(items=[], total=0, page=1, page_size=20)
    assert resp.total == 0
