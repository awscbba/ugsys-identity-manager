"""Unit tests for AuthService.validate_token and issue_service_token."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
from src.application.services.auth_service import AuthService
from src.domain.exceptions import AuthenticationError
from src.domain.value_objects.password_validator import PasswordValidator


@pytest.fixture
def deps() -> tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator]:
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    token_blacklist = AsyncMock()
    password_validator = PasswordValidator()
    hasher.verify.return_value = True
    return repo, token_svc, hasher, token_blacklist, password_validator


def test_validate_token_valid(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.verify_token.return_value = {
        "sub": "user-123",
        "roles": ["member"],
        "type": "access",
    }
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    result = svc.validate_token(ValidateTokenCommand(token="valid"))
    assert result["valid"] is True
    assert result["sub"] == "user-123"
    assert result["roles"] == ["member"]
    assert result["type"] == "access"


def test_validate_token_invalid_returns_valid_false(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = AuthService(repo, token_svc, hasher, token_blacklist, password_validator)
    result = svc.validate_token(ValidateTokenCommand(token="bad"))
    assert result["valid"] is False
    assert "sub" not in result


def test_issue_service_token_success(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    token_svc.create_service_token.return_value = "svc-token"
    service_accounts = {
        "projects-registry": {"secret": "hashed-secret", "roles": ["service"]},
    }
    svc = AuthService(
        repo,
        token_svc,
        hasher,
        token_blacklist,
        password_validator,
        service_accounts=service_accounts,
    )
    result = svc.issue_service_token(
        ServiceTokenCommand(client_id="projects-registry", client_secret="plain-secret")
    )
    assert result.access_token == "svc-token"
    assert result.refresh_token == ""


def test_issue_service_token_unknown_client_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    svc = AuthService(
        repo, token_svc, hasher, token_blacklist, password_validator, service_accounts={}
    )
    with pytest.raises(AuthenticationError) as exc_info:
        svc.issue_service_token(ServiceTokenCommand(client_id="unknown", client_secret="x"))
    assert exc_info.value.error_code == "INVALID_CLIENT_CREDENTIALS"


def test_issue_service_token_bad_secret_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock, AsyncMock, PasswordValidator],
) -> None:
    repo, token_svc, hasher, token_blacklist, password_validator = deps
    hasher.verify.return_value = False
    service_accounts = {
        "projects-registry": {"secret": "hashed-secret", "roles": ["service"]},
    }
    svc = AuthService(
        repo,
        token_svc,
        hasher,
        token_blacklist,
        password_validator,
        service_accounts=service_accounts,
    )
    with pytest.raises(AuthenticationError) as exc_info:
        svc.issue_service_token(
            ServiceTokenCommand(client_id="projects-registry", client_secret="wrong")
        )
    assert exc_info.value.error_code == "INVALID_CLIENT_CREDENTIALS"
