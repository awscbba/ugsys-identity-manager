"""Unit tests for AuthService.validate_token and issue_service_token."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.commands.service_token import ServiceTokenCommand, ValidateTokenCommand
from src.application.services.auth_service import AuthService


@pytest.fixture
def deps() -> tuple[AsyncMock, MagicMock, MagicMock]:
    repo = AsyncMock()
    token_svc = MagicMock()
    hasher = MagicMock()
    hasher.verify.return_value = True
    return repo, token_svc, hasher


def test_validate_token_valid(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    token_svc.verify_token.return_value = {
        "sub": "user-123",
        "roles": ["member"],
        "type": "access",
    }
    svc = AuthService(repo, token_svc, hasher)
    result = svc.validate_token(ValidateTokenCommand(token="valid"))
    assert result["sub"] == "user-123"
    assert result["roles"] == ["member"]


def test_validate_token_invalid_raises(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    token_svc.verify_token.side_effect = ValueError("expired")
    svc = AuthService(repo, token_svc, hasher)
    with pytest.raises(ValueError, match="Invalid or expired token"):
        svc.validate_token(ValidateTokenCommand(token="bad"))


def test_issue_service_token_success(deps: tuple[AsyncMock, MagicMock, MagicMock]) -> None:
    repo, token_svc, hasher = deps
    token_svc.create_service_token.return_value = "svc-token"
    service_accounts = {
        "projects-registry": {"secret": "hashed-secret", "roles": ["service"]},
    }
    svc = AuthService(repo, token_svc, hasher, service_accounts=service_accounts)
    result = svc.issue_service_token(
        ServiceTokenCommand(client_id="projects-registry", client_secret="plain-secret")
    )
    assert result.access_token == "svc-token"
    assert result.refresh_token == ""


def test_issue_service_token_unknown_client_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    svc = AuthService(repo, token_svc, hasher, service_accounts={})
    with pytest.raises(ValueError, match="Invalid client credentials"):
        svc.issue_service_token(ServiceTokenCommand(client_id="unknown", client_secret="x"))


def test_issue_service_token_bad_secret_raises(
    deps: tuple[AsyncMock, MagicMock, MagicMock],
) -> None:
    repo, token_svc, hasher = deps
    hasher.verify.return_value = False
    service_accounts = {
        "projects-registry": {"secret": "hashed-secret", "roles": ["service"]},
    }
    svc = AuthService(repo, token_svc, hasher, service_accounts=service_accounts)
    with pytest.raises(ValueError, match="Invalid client credentials"):
        svc.issue_service_token(
            ServiceTokenCommand(client_id="projects-registry", client_secret="wrong")
        )
