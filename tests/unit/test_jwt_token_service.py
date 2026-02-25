"""Unit tests for JWTTokenService adapter."""

from uuid import UUID, uuid4

import pytest

from src.domain.exceptions import AuthenticationError
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
    with pytest.raises(AuthenticationError, match="Invalid token"):
        svc.verify_token("not.a.valid.token")


def test_tampered_token_raises(svc: JWTTokenService) -> None:
    token = svc.create_access_token(uuid4(), roles=["member"])
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(AuthenticationError, match="Invalid token"):
        svc.verify_token(tampered)


def test_all_tokens_contain_jti_claim(svc: JWTTokenService) -> None:
    """Every token type must include a jti (UUID4) claim."""
    user_id = uuid4()
    access = svc.verify_token(svc.create_access_token(user_id, ["member"]))
    refresh = svc.verify_token(svc.create_refresh_token(user_id))
    reset = svc.verify_token(svc.create_password_reset_token(user_id, "a@b.com"))
    service = svc.verify_token(svc.create_service_token("client-1", ["admin"]))

    for payload in [access, refresh, reset, service]:
        jti = payload.get("jti")
        assert jti is not None, "Token missing jti claim"
        UUID(str(jti), version=4)  # validates it's a UUID4


def test_consecutive_tokens_have_different_jti(svc: JWTTokenService) -> None:
    """Two tokens created back-to-back must have unique jti values."""
    user_id = uuid4()
    t1 = svc.verify_token(svc.create_access_token(user_id, ["member"]))
    t2 = svc.verify_token(svc.create_access_token(user_id, ["member"]))
    assert t1["jti"] != t2["jti"]
