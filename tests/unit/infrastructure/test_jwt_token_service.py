"""Bug condition exploration tests — JWT algorithm enforcement (Gap 4).

**Validates: Requirements 1.14, 1.15, 1.16**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
"""

from __future__ import annotations

import contextlib
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

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

_HS256_ALGORITHM_TEST_VALUE = "test-hs256-secret-for-exploration-tests"


def _rs256_service() -> JWTTokenService:
    """Service configured for RS256 (correct config)."""
    return JWTTokenService(secret_key=_PRIVATE_KEY_PEM, algorithm="RS256")


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
    """Requirement 2.17/2.18: A service built from default settings accepts HS256 tokens.

    BUG: settings.jwt_algorithm defaults to 'HS256', so a service wired from
    settings will accept HS256-signed tokens. After the fix, the config validator
    must reject HS256 at startup.

    This test creates a service using the CURRENT DEFAULT algorithm from settings
    and verifies it accepts an HS256 token — proving the bug exists.
    Counterexample: HS256 token accepted by a service built from default settings.
    """
    # Build service using the current (buggy) default algorithm from settings
    svc = JWTTokenService(secret_key=_HS256_ALGORITHM_TEST_VALUE, algorithm=settings.jwt_algorithm)

    hs256_token: str = jwt.encode(
        {"sub": str(uuid4()), "exp": int(time.time()) + 3600, "iss": "test"},
        _HS256_ALGORITHM_TEST_VALUE,
        algorithm="HS256",
    )

    # On unfixed code: settings.jwt_algorithm == "HS256", so verify_token succeeds (bug)
    # On fixed code: settings.jwt_algorithm == "RS256", so this raises AuthenticationError
    if settings.jwt_algorithm == "HS256":
        # Bug confirmed: HS256 token accepted because config defaults to HS256
        with contextlib.suppress(AuthenticationError):
            svc.verify_token(hs256_token)
        pytest.fail(
            f"BUG CONFIRMED: settings.jwt_algorithm='{settings.jwt_algorithm}' — "
            "config defaults to HS256 instead of RS256. "
            "After fix, this must raise AuthenticationError."
        )
    else:
        # Fix applied: RS256 enforced, HS256 token rejected
        with pytest.raises(AuthenticationError):
            svc.verify_token(hs256_token)


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
    )

    with pytest.raises(AuthenticationError):
        svc.verify_token(token_without_iss)


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
    )

    with pytest.raises(AuthenticationError):
        svc.verify_token(token_without_sub)


# ═══════════════════════════════════════════════════════════════════════════════
# PRESERVATION TESTS — Property 2: Valid RS256 tokens must continue to be accepted
# **Validates: Requirements 3.2**
# These tests MUST PASS on unfixed code — they confirm the baseline to preserve.
# ═══════════════════════════════════════════════════════════════════════════════


def test_preservation_valid_rs256_token_with_all_required_claims_is_accepted() -> None:
    """Preservation 3.2: A valid RS256 token with all required claims must be accepted.

    This confirms the baseline: verify_token() returns the payload for a well-formed
    RS256 token containing sub, exp, iat, and iss. This must continue to work after
    the fix is applied.
    """
    # Use public key PEM for verification (correct RS256 usage)
    public_key_pem = (
        _PRIVATE_KEY.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    svc = JWTTokenService(secret_key=public_key_pem, algorithm="RS256")

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
    )

    payload = svc.verify_token(token)

    assert payload is not None
    assert "sub" in payload
    assert "iss" in payload
