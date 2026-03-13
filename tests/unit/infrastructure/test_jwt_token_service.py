"""Bug condition exploration tests — JWT algorithm enforcement (Gap 4).

**Validates: Requirements 1.14, 1.15, 1.16**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import serialization as _serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

from src.config import settings
from src.domain.exceptions import AuthenticationError
from src.infrastructure.adapters.jwt_token_service import JWTTokenService

# ── RSA key pair for RS256 tests ─────────────────────────────────────────────

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_KEY_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_KEY_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

_HS256_ALGORITHM_TEST_VALUE = "test-hs256-secret-for-exploration-tests"


def _rs256_service() -> JWTTokenService:
    """Service configured for RS256 (correct config)."""
    return JWTTokenService(private_key=_PRIVATE_KEY_PEM, public_key=_PUBLIC_KEY_PEM, key_id="test")


# ── Bug 1.14: jwt_algorithm defaults to HS256 ────────────────────────────────


def test_settings_jwt_algorithm_is_rs256() -> None:
    """Requirement 2.17: settings.jwt_algorithm must default to 'RS256'.

    BUG: currently defaults to 'HS256'.
    Counterexample: settings.jwt_algorithm == 'HS256'
    """
    assert settings.jwt_algorithm == "RS256", (
        f"Expected settings.jwt_algorithm == 'RS256' but got '{settings.jwt_algorithm}'. "
        "BUG: config defaults to HS256."
    )


# ── Bug 1.15: algorithm not pre-checked before jwt.decode() ──────────────────


def test_verify_token_pre_checks_algorithm_header() -> None:
    """Requirement 2.18: verify_token() must call get_unverified_header() BEFORE decode.

    BUG: the current implementation does NOT call get_unverified_header() before
    jwt.decode(). The only 'none' check is a post-decode payload inspection
    (`payload.get("alg") == "none"`), which is wrong — alg is in the JWT header,
    not the payload. The fix must inspect the header first.
    Counterexample: verify_token() source has no get_unverified_header() call.
    """
    import inspect

    source = inspect.getsource(JWTTokenService.verify_token)
    assert "get_unverified_header" in source, (
        "Expected verify_token() to call jwt.get_unverified_header() before jwt.decode() "
        "to enforce algorithm restriction, but the call was not found. "
        "BUG: algorithm header is not pre-checked before signature verification."
    )


# ── Bug 1.15: HS256 token accepted when service uses default HS256 config ────


def test_hs256_token_accepted_by_default_config_service() -> None:
    """Requirement 2.17/2.18: settings.jwt_algorithm must be RS256 and HS256 tokens rejected.

    With the fix applied: settings.jwt_algorithm == "RS256", so a service built from
    settings rejects HS256-signed tokens.
    """
    assert settings.jwt_algorithm == "RS256"

    svc = JWTTokenService(
        private_key=_PRIVATE_KEY_PEM,
        public_key=_PUBLIC_KEY_PEM,
        key_id="test",
    )

    hs256_token: str = jwt.encode(
        {"sub": str(uuid4()), "exp": int(time.time()) + 3600, "iss": "test"},
        _HS256_ALGORITHM_TEST_VALUE,
        algorithm="HS256",
    )

    # RS256 service must reject HS256 token
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.verify_token(hs256_token))


# ── Bug 1.16: Token missing 'iss' claim accepted ─────────────────────────────


def test_token_missing_iss_claim_rejected() -> None:
    """Requirement 2.19: Tokens missing the 'iss' claim must be rejected.

    BUG: currently no required-claims validation is performed after decode.
    Counterexample: token without 'iss' is accepted and payload returned.
    """
    svc = _rs256_service()

    token_without_iss: str = jwt.encode(
        {
            "sub": str(uuid4()),
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            # 'iss' intentionally omitted
        },
        _PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"kid": "test"},
    )

    with pytest.raises(AuthenticationError):
        asyncio.run(svc.verify_token(token_without_iss))


# ── Bug 1.16: Token missing 'sub' claim accepted ─────────────────────────────


def test_token_missing_sub_claim_rejected() -> None:
    """Requirement 2.19: Tokens missing the 'sub' claim must be rejected.

    BUG: currently no required-claims validation is performed after decode.
    Counterexample: token without 'sub' is accepted and payload returned.
    """
    svc = _rs256_service()

    token_without_sub: str = jwt.encode(
        {
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "iss": "https://cognito.example.com/us-east-1_test",
            # 'sub' intentionally omitted
        },
        _PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"kid": "test"},
    )

    with pytest.raises(AuthenticationError):
        asyncio.run(svc.verify_token(token_without_sub))


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION TESTS — Property 2: Valid RS256 tokens must continue to be accepted
# **Validates: Requirements 3.2**
# These tests MUST PASS on unfixed code — they confirm the baseline to preserve.
# ═══════════════════════════════════════════════════════════════════════════════


def test_preservation_valid_rs256_token_with_all_required_claims_is_accepted() -> None:
    """Preservation 3.2: A valid RS256 token with all required claims must be accepted."""
    svc = JWTTokenService(
        private_key=_PRIVATE_KEY_PEM,
        public_key=_PUBLIC_KEY_PEM,
        key_id="test",
    )

    now = int(time.time())
    token: str = jwt.encode(
        {
            "sub": str(uuid4()),
            "exp": now + 3600,
            "iat": now,
            "iss": "https://cognito.example.com/us-east-1_test",
        },
        _PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"kid": "test"},
    )

    payload = asyncio.run(svc.verify_token(token))

    assert payload is not None
    assert "sub" in payload
    assert "iss" in payload


# ═══════════════════════════════════════════════════════════════════════════════
# Task 4.3 — multi-key, async, and JWKS tests
# Feature: im-security-hardening
# ═══════════════════════════════════════════════════════════════════════════════

# Generate a second (retiring) key pair for rotation tests
_RETIRING_PRIVATE_KEY = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
_RETIRING_PRIVATE_KEY_PEM = _RETIRING_PRIVATE_KEY.private_bytes(
    encoding=_serialization.Encoding.PEM,
    format=_serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=_serialization.NoEncryption(),
).decode()
_RETIRING_PUBLIC_KEY_PEM = (
    _RETIRING_PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=_serialization.Encoding.PEM,
        format=_serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def _service_with_retiring_key() -> JWTTokenService:
    return JWTTokenService(
        private_key=_PRIVATE_KEY_PEM,
        public_key=_PUBLIC_KEY_PEM,
        key_id="active-key",
        retiring_public_key=_RETIRING_PUBLIC_KEY_PEM,
        retiring_key_id="retiring-key",
    )


def _token_signed_with_retiring_key(audience: str = "admin-panel") -> str:
    """Encode a token using the retiring private key with kid=retiring-key."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "type": "access",
            "aud": audience,
            "exp": now + 3600,
            "iat": now,
            "iss": "ugsys-identity-manager",
            "jti": str(uuid4()),
        },
        _RETIRING_PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"kid": "retiring-key"},
    )


def test_verify_with_retiring_key_succeeds() -> None:
    """Token signed with retiring key verifies successfully when retiring key is configured."""
    svc = _service_with_retiring_key()
    token = _token_signed_with_retiring_key()
    payload = asyncio.run(svc.verify_token(token))
    assert payload["sub"] is not None


def test_unknown_kid_raises_authentication_error() -> None:
    """Token with unknown kid raises AuthenticationError(error_code='INVALID_TOKEN')."""
    svc = _rs256_service()
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "exp": now + 3600,
            "iat": now,
            "iss": "ugsys-identity-manager",
            "jti": str(uuid4()),
        },
        _PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"kid": "unknown-kid-xyz"},
    )
    with pytest.raises(AuthenticationError) as exc_info:
        asyncio.run(svc.verify_token(token))
    assert exc_info.value.error_code == "INVALID_TOKEN"


def test_jwks_includes_retiring_key_when_present() -> None:
    """get_jwks() returns two keys when retiring key is configured."""
    svc = _service_with_retiring_key()
    jwks = svc.get_jwks()
    assert isinstance(jwks["keys"], list)
    assert len(jwks["keys"]) == 2  # type: ignore[arg-type]
    kids = {k["kid"] for k in jwks["keys"]}  # type: ignore[index]
    assert "active-key" in kids
    assert "retiring-key" in kids


def test_jwks_single_key_when_no_retiring_key() -> None:
    """get_jwks() returns one key when no retiring key is configured."""
    svc = _rs256_service()
    jwks = svc.get_jwks()
    assert len(jwks["keys"]) == 1  # type: ignore[arg-type]


def test_blacklisted_token_raises_token_revoked() -> None:
    """Blacklisted jti raises AuthenticationError(error_code='TOKEN_REVOKED')."""
    blacklist = AsyncMock()
    blacklist.is_blacklisted = AsyncMock(return_value=True)

    svc = JWTTokenService(
        private_key=_PRIVATE_KEY_PEM,
        public_key=_PUBLIC_KEY_PEM,
        key_id="test",
        token_blacklist=blacklist,
    )
    token = svc.create_access_token(user_id=uuid4(), email="x@x.com", roles=[])

    with pytest.raises(AuthenticationError) as exc_info:
        asyncio.run(svc.verify_token(token))
    assert exc_info.value.error_code == "TOKEN_REVOKED"


def test_verify_token_is_async() -> None:
    """verify_token must be a coroutine function (async def)."""
    import inspect

    assert inspect.iscoroutinefunction(JWTTokenService.verify_token)
