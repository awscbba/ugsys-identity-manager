"""Smoke test for dependency wiring — Task 12.1.

Verifies create_app() completes without error and app.state has the
expected services after lifespan startup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI


class TestDependencyWiring:
    def test_create_app_returns_fastapi(self) -> None:
        import src.main as main_module

        app = main_module.create_app()
        assert isinstance(app, FastAPI)

    def test_wired_app_has_auth_service_override(self) -> None:
        """After _wire_dependencies, get_auth_service dependency is overridden."""
        import src.main as main_module
        from src.presentation.api.v1.auth import get_auth_service

        mock_session = MagicMock()
        mock_dynamodb = AsyncMock()
        mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_dynamodb)
        mock_session.client.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.main.aioboto3") as mock_aioboto3:
            mock_aioboto3.Session.return_value = mock_session
            app = main_module.create_app()
            main_module._wire_dependencies(app)

        assert get_auth_service in app.dependency_overrides

    def test_wired_app_has_user_service_override(self) -> None:
        """After _wire_dependencies, get_user_service dependency is overridden."""
        import src.main as main_module
        from src.presentation.api.v1.users import get_user_service

        mock_session = MagicMock()

        with patch("src.main.aioboto3") as mock_aioboto3:
            mock_aioboto3.Session.return_value = mock_session
            app = main_module.create_app()
            main_module._wire_dependencies(app)

        assert get_user_service in app.dependency_overrides

    def test_wired_auth_service_has_outbox_repo(self) -> None:
        """After wiring, AuthService instance has outbox_repo set (not None)."""
        import src.main as main_module
        from src.application.services.auth_service import AuthService
        from src.presentation.api.v1.auth import get_auth_service

        mock_session = MagicMock()

        with patch("src.main.aioboto3") as mock_aioboto3:
            mock_aioboto3.Session.return_value = mock_session
            app = main_module.create_app()
            main_module._wire_dependencies(app)

        auth_service = app.dependency_overrides[get_auth_service]()
        assert isinstance(auth_service, AuthService)
        assert auth_service._outbox_repo is not None

    def test_wired_auth_service_has_unit_of_work(self) -> None:
        """After wiring, AuthService instance has unit_of_work set (not None)."""
        import src.main as main_module
        from src.application.services.auth_service import AuthService
        from src.presentation.api.v1.auth import get_auth_service

        mock_session = MagicMock()

        with patch("src.main.aioboto3") as mock_aioboto3:
            mock_aioboto3.Session.return_value = mock_session
            app = main_module.create_app()
            main_module._wire_dependencies(app)

        auth_service = app.dependency_overrides[get_auth_service]()
        assert isinstance(auth_service, AuthService)
        assert auth_service._unit_of_work is not None


class TestOutboxTableConfig:
    def test_outbox_table_uses_override_when_set(self) -> None:
        from src.config import Settings

        s = Settings(outbox_table_name="my-custom-outbox")
        assert s.outbox_table == "my-custom-outbox"

    def test_outbox_table_computed_from_environment(self) -> None:
        from src.config import Settings

        s = Settings(environment="staging", outbox_table_name="")
        assert s.outbox_table == "ugsys-outbox-identity-staging"

    def test_outbox_table_default_uses_dev(self) -> None:
        from src.config import Settings

        s = Settings(environment="dev", outbox_table_name="")
        assert s.outbox_table == "ugsys-outbox-identity-dev"
