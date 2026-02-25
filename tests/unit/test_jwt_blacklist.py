"""Unit tests for JWTTokenService blacklist integration and uncovered paths."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.domain.exceptions import AuthenticationError
from src.infrastructure.adapters.jwt_token_service import JWTTokenService

_SECRET = "test-secret-key-for-unit-tests-only"


@pytest.fixture
def svc_no_blacklist() -> JWTTokenService:
    return JWTTokenService(secret_key=_SECRET, algorithm="HS256")


def test_verify_token_raises_when_blacklisted() -> None:
    """verify_token must raise TOKEN_REVOKED when jti is in the blacklist."""
    blacklist = AsyncMock()
    blacklist.is_blacklisted.return_value = True

    svc = JWTTokenService(secret_key=_SECRET, algorithm="HS256", token_blacklist=blacklist)
    token = svc.create_access_token(uuid4(), roles=["member"])

    with pytest.raises(AuthenticationError) as exc_info:
        svc.verify_token(token)

    assert exc_info.value.error_code == "TOKEN_REVOKED"


def test_verify_token_passes_when_not_blacklisted() -> None:
    """verify_token must succeed when jti is NOT in the blacklist."""
    blacklist = AsyncMock()
    blacklist.is_blacklisted.return_value = False

    svc = JWTTokenService(secret_key=_SECRET, algorithm="HS256", token_blacklist=blacklist)
    user_id = uuid4()
    token = svc.create_access_token(user_id, roles=["member"])

    payload = svc.verify_token(token)
    assert payload["sub"] == str(user_id)


def test_verify_token_skips_blacklist_when_not_configured(
    svc_no_blacklist: JWTTokenService,
) -> None:
    """When no blacklist is configured, verify_token must not attempt any blacklist check."""
    user_id = uuid4()
    token = svc_no_blacklist.create_access_token(user_id, roles=["member"])
    payload = svc_no_blacklist.verify_token(token)
    assert payload["sub"] == str(user_id)


def test_verify_token_none_algorithm_rejected(svc_no_blacklist: JWTTokenService) -> None:
    """Tokens with alg=none must be rejected."""
    # Craft a token that would pass if alg=none were accepted
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(
        b"="
    )
    payload_b = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "type": "access"}).encode()
    ).rstrip(b"=")
    forged = f"{header.decode()}.{payload_b.decode()}."

    with pytest.raises(AuthenticationError):
        svc_no_blacklist.verify_token(forged)


def test_password_reset_token_has_email_claim(svc_no_blacklist: JWTTokenService) -> None:
    user_id = uuid4()
    token = svc_no_blacklist.create_password_reset_token(user_id, "user@example.com")
    payload = svc_no_blacklist.verify_token(token)
    assert payload["email"] == "user@example.com"
    assert payload["type"] == "password_reset"


def test_service_token_has_correct_claims(svc_no_blacklist: JWTTokenService) -> None:
    token = svc_no_blacklist.create_service_token("projects-registry", ["service"])
    payload = svc_no_blacklist.verify_token(token)
    assert payload["sub"] == "projects-registry"
    assert payload["type"] == "service"
    assert "service" in payload["roles"]
