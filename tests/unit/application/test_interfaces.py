"""Interface compliance tests — Task 11.1 (TDD RED phase).

Verifies:
- IAuthService and IUserService are importable ABCs
- AuthService is a subclass of IAuthService
- UserService is a subclass of IUserService
- All abstract methods declared on each interface are implemented on the concrete class
"""

from __future__ import annotations

import inspect


class TestIAuthServiceImportable:
    def test_iauth_service_importable(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert IAuthService is not None

    def test_iauth_service_is_abstract(self) -> None:
        import abc

        from src.application.interfaces.auth_service import IAuthService

        assert issubclass(IAuthService, abc.ABC)

    def test_auth_service_is_subclass_of_iauth_service(self) -> None:
        from src.application.interfaces.auth_service import IAuthService
        from src.application.services.auth_service import AuthService

        assert issubclass(AuthService, IAuthService)

    def test_iauth_service_declares_register(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "register")
        assert getattr(IAuthService.register, "__isabstractmethod__", False)

    def test_iauth_service_declares_authenticate(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "authenticate")
        assert getattr(IAuthService.authenticate, "__isabstractmethod__", False)

    def test_iauth_service_declares_refresh(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "refresh")
        assert getattr(IAuthService.refresh, "__isabstractmethod__", False)

    def test_iauth_service_declares_forgot_password(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "forgot_password")
        assert getattr(IAuthService.forgot_password, "__isabstractmethod__", False)

    def test_iauth_service_declares_reset_password(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "reset_password")
        assert getattr(IAuthService.reset_password, "__isabstractmethod__", False)

    def test_iauth_service_declares_validate_token(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "validate_token")
        assert getattr(IAuthService.validate_token, "__isabstractmethod__", False)

    def test_iauth_service_declares_issue_service_token(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "issue_service_token")
        assert getattr(IAuthService.issue_service_token, "__isabstractmethod__", False)

    def test_iauth_service_declares_verify_email(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "verify_email")
        assert getattr(IAuthService.verify_email, "__isabstractmethod__", False)

    def test_iauth_service_declares_resend_verification(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "resend_verification")
        assert getattr(IAuthService.resend_verification, "__isabstractmethod__", False)

    def test_iauth_service_declares_logout(self) -> None:
        from src.application.interfaces.auth_service import IAuthService

        assert hasattr(IAuthService, "logout")
        assert getattr(IAuthService.logout, "__isabstractmethod__", False)

    def test_auth_service_implements_all_abstract_methods(self) -> None:
        from src.application.interfaces.auth_service import IAuthService
        from src.application.services.auth_service import AuthService

        abstract_methods = {
            name
            for name, method in inspect.getmembers(IAuthService, predicate=inspect.isfunction)
            if getattr(method, "__isabstractmethod__", False)
        }
        for method_name in abstract_methods:
            assert hasattr(AuthService, method_name), (
                f"AuthService missing implementation of abstract method: {method_name}"
            )


class TestIUserServiceImportable:
    def test_iuser_service_importable(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert IUserService is not None

    def test_iuser_service_is_abstract(self) -> None:
        import abc

        from src.application.interfaces.user_service import IUserService

        assert issubclass(IUserService, abc.ABC)

    def test_user_service_is_subclass_of_iuser_service(self) -> None:
        from src.application.interfaces.user_service import IUserService
        from src.application.services.user_service import UserService

        assert issubclass(UserService, IUserService)

    def test_iuser_service_declares_get_user(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "get_user")
        assert getattr(IUserService.get_user, "__isabstractmethod__", False)

    def test_iuser_service_declares_update_profile(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "update_profile")
        assert getattr(IUserService.update_profile, "__isabstractmethod__", False)

    def test_iuser_service_declares_assign_role(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "assign_role")
        assert getattr(IUserService.assign_role, "__isabstractmethod__", False)

    def test_iuser_service_declares_remove_role(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "remove_role")
        assert getattr(IUserService.remove_role, "__isabstractmethod__", False)

    def test_iuser_service_declares_deactivate(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "deactivate")
        assert getattr(IUserService.deactivate, "__isabstractmethod__", False)

    def test_iuser_service_declares_list_users(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "list_users")
        assert getattr(IUserService.list_users, "__isabstractmethod__", False)

    def test_iuser_service_declares_get_user_roles(self) -> None:
        from src.application.interfaces.user_service import IUserService

        assert hasattr(IUserService, "get_user_roles")
        assert getattr(IUserService.get_user_roles, "__isabstractmethod__", False)

    def test_user_service_implements_all_abstract_methods(self) -> None:
        from src.application.interfaces.user_service import IUserService
        from src.application.services.user_service import UserService

        abstract_methods = {
            name
            for name, method in inspect.getmembers(IUserService, predicate=inspect.isfunction)
            if getattr(method, "__isabstractmethod__", False)
        }
        for method_name in abstract_methods:
            assert hasattr(UserService, method_name), (
                f"UserService missing implementation of abstract method: {method_name}"
            )
