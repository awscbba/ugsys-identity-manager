"""Unit tests for Settings config."""

from src.config import Settings


def test_users_table_property() -> None:
    s = Settings(environment="staging")
    assert s.users_table == "ugsys-identity-manager-users-staging"


def test_users_table_override() -> None:
    s = Settings(dynamodb_table_name="custom-table", environment="staging")
    assert s.users_table == "custom-table"


def test_defaults() -> None:
    s = Settings()
    assert s.service_name == "ugsys-identity-manager"
    assert s.aws_region == "us-east-1"
    assert s.xray_enabled is False
    assert s.version == "0.1.0"
    assert s.event_bus_name == "ugsys-platform-bus"
    assert s.token_blacklist_table_name == ""


def test_token_blacklist_table_property() -> None:
    s = Settings(environment="staging")
    assert s.token_blacklist_table == "ugsys-identity-staging-token-blacklist"


def test_token_blacklist_table_override() -> None:
    s = Settings(token_blacklist_table_name="custom-blacklist", environment="staging")
    assert s.token_blacklist_table == "custom-blacklist"


def test_cookie_settings_defaults() -> None:
    s = Settings()
    assert s.cookie_domain == ".apps.cloud.org.bo"
    assert s.cookie_secure is True
    assert s.refresh_token_cookie_name == "ugsys_refresh_token"
    assert "https://profile.apps.cloud.org.bo" in s.cors_origins


def test_cookie_secure_overridable_via_env(monkeypatch: object) -> None:
    import pytest

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("COOKIE_SECURE", "false")
        s = Settings()
        assert s.cookie_secure is False
