"""Task 11.1 — IAuthService and IUserService interface compliance tests."""

import inspect

from src.application.interfaces.auth_service import IAuthService
from src.application.interfaces.user_service import IUserService
from src.application.services.auth_service import AuthService
from src.application.services.user_service import UserService

# ── IAuthService compliance ───────────────────────────────────────────────────


def test_auth_service_is_subclass_of_iauth_service() -> None:
    assert issubclass(AuthService, IAuthService)


def test_auth_service_instance_is_iauth_service() -> None:
    # All abstract methods must be implemented — instantiation would fail otherwise
    abstract_methods = {
        name
        for name, _ in inspect.getmembers(IAuthService, predicate=inspect.isfunction)
        if getattr(getattr(IAuthService, name), "__isabstractmethod__", False)
    }
    implemented = set(dir(AuthService))
    missing = abstract_methods - implemented
    assert not missing, f"AuthService missing abstract methods: {missing}"


def test_iauth_service_declares_register() -> None:
    assert hasattr(IAuthService, "register")
    assert getattr(IAuthService.register, "__isabstractmethod__", False)


def test_iauth_service_declares_authenticate() -> None:
    assert hasattr(IAuthService, "authenticate")
    assert getattr(IAuthService.authenticate, "__isabstractmethod__", False)


def test_iauth_service_declares_refresh() -> None:
    assert hasattr(IAuthService, "refresh")
    assert getattr(IAuthService.refresh, "__isabstractmethod__", False)


def test_iauth_service_declares_forgot_password() -> None:
    assert hasattr(IAuthService, "forgot_password")
    assert getattr(IAuthService.forgot_password, "__isabstractmethod__", False)


def test_iauth_service_declares_reset_password() -> None:
    assert hasattr(IAuthService, "reset_password")
    assert getattr(IAuthService.reset_password, "__isabstractmethod__", False)


def test_iauth_service_declares_validate_token() -> None:
    assert hasattr(IAuthService, "validate_token")
    assert getattr(IAuthService.validate_token, "__isabstractmethod__", False)


def test_iauth_service_declares_issue_service_token() -> None:
    assert hasattr(IAuthService, "issue_service_token")
    assert getattr(IAuthService.issue_service_token, "__isabstractmethod__", False)


def test_iauth_service_declares_verify_email() -> None:
    assert hasattr(IAuthService, "verify_email")
    assert getattr(IAuthService.verify_email, "__isabstractmethod__", False)


def test_iauth_service_declares_resend_verification() -> None:
    assert hasattr(IAuthService, "resend_verification")
    assert getattr(IAuthService.resend_verification, "__isabstractmethod__", False)


def test_iauth_service_declares_logout() -> None:
    assert hasattr(IAuthService, "logout")
    assert getattr(IAuthService.logout, "__isabstractmethod__", False)


# ── IUserService compliance ───────────────────────────────────────────────────


def test_user_service_is_subclass_of_iuser_service() -> None:
    assert issubclass(UserService, IUserService)


def test_user_service_implements_all_abstract_methods() -> None:
    abstract_methods = {
        name
        for name, _ in inspect.getmembers(IUserService, predicate=inspect.isfunction)
        if getattr(getattr(IUserService, name), "__isabstractmethod__", False)
    }
    implemented = set(dir(UserService))
    missing = abstract_methods - implemented
    assert not missing, f"UserService missing abstract methods: {missing}"


def test_iuser_service_declares_get_user() -> None:
    assert hasattr(IUserService, "get_user")
    assert getattr(IUserService.get_user, "__isabstractmethod__", False)


def test_iuser_service_declares_update_profile() -> None:
    assert hasattr(IUserService, "update_profile")
    assert getattr(IUserService.update_profile, "__isabstractmethod__", False)


def test_iuser_service_declares_list_users() -> None:
    assert hasattr(IUserService, "list_users")
    assert getattr(IUserService.list_users, "__isabstractmethod__", False)


def test_iuser_service_declares_get_user_roles() -> None:
    assert hasattr(IUserService, "get_user_roles")
    assert getattr(IUserService.get_user_roles, "__isabstractmethod__", False)
