"""Unit tests verifying application DTOs are importable and correct.

TDD: RED phase — tests written before implementation.
"""

from __future__ import annotations

import html
from uuid import uuid4


class TestAuthDtosImportable:
    def test_register_user_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import RegisterUserRequest

        assert RegisterUserRequest is not None

    def test_login_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import LoginRequest

        assert LoginRequest is not None

    def test_refresh_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import RefreshRequest

        assert RefreshRequest is not None

    def test_forgot_password_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import ForgotPasswordRequest

        assert ForgotPasswordRequest is not None

    def test_reset_password_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import ResetPasswordRequest

        assert ResetPasswordRequest is not None

    def test_verify_email_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import VerifyEmailRequest

        assert VerifyEmailRequest is not None

    def test_resend_verification_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import ResendVerificationRequest

        assert ResendVerificationRequest is not None

    def test_service_token_request_importable(self) -> None:
        from src.application.dtos.auth_dtos import ServiceTokenRequest

        assert ServiceTokenRequest is not None

    def test_token_response_importable(self) -> None:
        from src.application.dtos.auth_dtos import TokenResponse

        assert TokenResponse is not None

    def test_service_token_response_importable(self) -> None:
        from src.application.dtos.auth_dtos import ServiceTokenResponse

        assert ServiceTokenResponse is not None


class TestUserDtosImportable:
    def test_user_response_importable(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        assert UserResponse is not None

    def test_update_profile_request_importable(self) -> None:
        from src.application.dtos.user_dtos import UpdateProfileRequest

        assert UpdateProfileRequest is not None

    def test_assign_role_request_importable(self) -> None:
        from src.application.dtos.user_dtos import AssignRoleRequest

        assert AssignRoleRequest is not None

    def test_paginated_users_response_importable(self) -> None:
        from src.application.dtos.user_dtos import PaginatedUsersResponse

        assert PaginatedUsersResponse is not None


class TestRegisterUserRequestValidator:
    def test_sanitize_name_strips_whitespace(self) -> None:
        from src.application.dtos.auth_dtos import RegisterUserRequest

        req = RegisterUserRequest(
            email="dev@example.com",
            password="Str0ng!Pass",
            full_name="  Test User  ",
        )
        assert req.full_name == "Test User"

    def test_sanitize_name_escapes_html(self) -> None:
        from src.application.dtos.auth_dtos import RegisterUserRequest

        req = RegisterUserRequest(
            email="dev@example.com",
            password="Str0ng!Pass",
            full_name="<script>alert(1)</script>",
        )
        assert "<script>" not in req.full_name
        assert req.full_name == html.escape("<script>alert(1)</script>")

    def test_sanitize_name_strips_and_escapes(self) -> None:
        from src.application.dtos.auth_dtos import RegisterUserRequest

        req = RegisterUserRequest(
            email="dev@example.com",
            password="Str0ng!Pass",
            full_name="  <b>Bold</b>  ",
        )
        assert req.full_name == html.escape("<b>Bold</b>")


class TestUserResponseFromDomain:
    def _make_user(self) -> object:
        from src.domain.entities.user import User, UserStatus

        return User(
            id=uuid4(),
            email="dev@example.com",
            full_name="Dev User",
            hashed_password="hashed",
            status=UserStatus.ACTIVE,
        )

    def test_from_domain_returns_user_response(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert isinstance(response, UserResponse)

    def test_from_domain_maps_id(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert str(response.id) == str(user.id)  # type: ignore[attr-defined]

    def test_from_domain_maps_email(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert response.email == "dev@example.com"

    def test_from_domain_maps_full_name(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert response.full_name == "Dev User"

    def test_from_domain_maps_status(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert response.status == "active"

    def test_from_domain_maps_roles(self) -> None:
        from src.application.dtos.user_dtos import UserResponse

        user = self._make_user()
        response = UserResponse.from_domain(user)  # type: ignore[arg-type]
        assert isinstance(response.roles, list)
