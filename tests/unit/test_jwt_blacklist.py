"""Unit tests for JWTTokenService blacklist integration and uncovered paths."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.exceptions import AuthenticationError
from src.infrastructure.adapters.jwt_token_service import JWTTokenService


def _generate_rsa_key_pair() -> tuple[str, str]:
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
def svc_no_blacklist() -> JWTTokenService:
    return JWTTokenService(
        private_key=_PRIVATE_KEY,
        public_key=_PUBLIC_KEY,
        key_id="test-key",
    )


def test_verify_token_raises_when_blacklisted() -> None:
    """verify_token must raise AuthenticationError when jti is in the blacklist."""
    blacklist = AsyncMock()
    blacklist.is_blacklisted.return_value = True

    svc = JWTTokenService(
        private_key=_PRIVATE_KEY,
        public_key=_PUBLIC_KEY,
        key_id="test-key",
        token_blacklist=blacklist,
    )
    token = svc.create_access_token(uuid4(), email="user@example.com", roles=["member"])

    with pytest.raises(AuthenticationError):
        svc.verify_token(token)


def test_verify_token_passes_when_not_blacklisted() -> None:
    """verify_token must succeed when jti is NOT in the blacklist."""
    blacklist = AsyncMock()
    blacklist.is_blacklisted.return_value = False

    svc = JWTTokenService(
        private_key=_PRIVATE_KEY,
        public_key=_PUBLIC_KEY,
        key_id="test-key",
        token_blacklist=blacklist,
    )
    user_id = uuid4()
    token = svc.create_access_token(user_id, email="user@example.com", roles=["member"])

    payload = svc.verify_token(token)
    assert payload["sub"] == str(user_id)


def test_verify_token_skips_blacklist_when_not_configured(
    svc_no_blacklist: JWTTokenService,
) -> None:
    """When no blacklist is configured, verify_token must not attempt any blacklist check."""
    user_id = uuid4()
    token = svc_no_blacklist.create_access_token(
        user_id, email="user@example.com", roles=["member"]
    )
    payload = svc_no_blacklist.verify_token(token)
    assert payload["sub"] == str(user_id)


def test_verify_token_none_algorithm_rejected(svc_no_blacklist: JWTTokenService) -> None:
    """Tokens with alg=none must be rejected."""
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
