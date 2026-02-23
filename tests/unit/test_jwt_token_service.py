"""Unit tests for JWTTokenService adapter."""

from uuid import uuid4

import pytest

from src.infrastructure.adapters.jwt_token_service import JWTTokenService

_SECRET = "test-secret-key-for-unit-tests-only"


@pytest.fixture
def svc() -> JWTTokenService:
    # Use HS256 in tests — RS256 requires a real RSA key pair
    return JWTTokenService(secret_key=_SECRET, algorithm="HS256")


def test_create_and_verify_access_token(svc: JWTTokenService) -> None:
    user_id = uuid4()
    token = svc.create_access_token(user_id=user_id, roles=["member"])
    payload = svc.verify_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert payload["roles"] == ["member"]


def test_create_and_verify_refresh_token(svc: JWTTokenService) -> None:
    user_id = uuid4()
    token = svc.create_refresh_token(user_id=user_id)
    payload = svc.verify_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"


def test_invalid_token_raises(svc: JWTTokenService) -> None:
    with pytest.raises(ValueError, match="Invalid token"):
        svc.verify_token("not.a.valid.token")


def test_tampered_token_raises(svc: JWTTokenService) -> None:
    token = svc.create_access_token(uuid4(), roles=["member"])
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(ValueError, match="Invalid token"):
        svc.verify_token(tampered)
