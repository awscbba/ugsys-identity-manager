"""Unit tests for Settings config."""

from src.config import Settings


def test_users_table_property() -> None:
    s = Settings(dynamodb_table_prefix="myprefix", environment="staging")
    assert s.users_table == "myprefix-identity-users-staging"


def test_defaults() -> None:
    s = Settings()
    assert s.service_name == "ugsys-identity-manager"
    assert s.aws_region == "us-east-1"
    assert s.xray_enabled is False
