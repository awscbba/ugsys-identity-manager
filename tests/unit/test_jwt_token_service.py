"""Unit tests for JWTTokenService adapter."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.exceptions import AuthenticationError
from src.infrastructure.adapters.jwt_token_service import JWTTokenService


def _generate_rsa_key_pair() -> tuple[str, str]:
    """Generate a test RSA key pair. Returns (private_key_pem, public_key_pem)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


_PRIVATE_KEY, _PUBLIC_KEY = _generate_rsa_key_pair()


@pytest.fixture
def svc() -> JWTTokenService:
    """RS256 service using a generated test RSA key pair."""
    return JWTTokenService(
        private_key=_PRIVATE_KEY,
        public_key=_PUBLIC_KEY,
        key_id="test-key",
    )


def test_create_and_verify_access_token(svc: JWTTokenService) -> None:
    user_id = uuid4()
    token = svc.create_access_token(user_id=user_id, email="user@example.com", roles=["member"])
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
    token = svc.create_access_token(uuid4(), email="user@example.com", roles=["member"])
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(AuthenticationError):
        svc.verify_token(tampered)


def test_all_tokens_contain_jti_claim(svc: JWTTokenService) -> None:
    """Every token type must include a jti (UUID4) claim."""
    user_id = uuid4()
    access = svc.verify_token(svc.create_access_token(user_id, "user@example.com", ["member"]))
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
    t1 = svc.verify_token(svc.create_access_token(user_id, "user@example.com", ["member"]))
    t2 = svc.verify_token(svc.create_access_token(user_id, "user@example.com", ["member"]))
    assert t1["jti"] != t2["jti"]
