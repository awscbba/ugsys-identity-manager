"""JWT token service — adapter implementing TokenService port.

Uses RS256 exclusively:
  - private_key (PEM) — signs tokens
  - public_key  (PEM) — verifies tokens, exposed via JWKS endpoint
  - key_id            — included as 'kid' in JWT header and JWKS
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from jose import JWTError, jwt

from src.domain.exceptions import AuthenticationError
from src.domain.repositories.token_blacklist_repository import TokenBlacklistRepository
from src.domain.repositories.token_service import TokenService


class JWTTokenService(TokenService):
    def __init__(
        self,
        private_key: str,
        public_key: str,
        key_id: str = "ugsys-v1",
        token_blacklist: TokenBlacklistRepository | None = None,
    ) -> None:
        self._private_key = private_key
        self._public_key = public_key
        self._key_id = key_id
        self._token_blacklist = token_blacklist
        self._access_ttl = timedelta(minutes=30)
        self._refresh_ttl = timedelta(days=7)
        self._reset_ttl = timedelta(hours=1)
        self._service_ttl = timedelta(hours=1)

    # ── Token creation ────────────────────────────────────────────────────────

    def create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str:
        return self._encode(
            {"sub": str(user_id), "email": email, "roles": roles, "type": "access"},
            self._access_ttl,
        )

    def create_refresh_token(self, user_id: UUID) -> str:
        return self._encode({"sub": str(user_id), "type": "refresh"}, self._refresh_ttl)

    def create_password_reset_token(self, user_id: UUID, email: str) -> str:
        return self._encode(
            {"sub": str(user_id), "email": email, "type": "password_reset"},
            self._reset_ttl,
        )

    def create_service_token(self, client_id: str, roles: list[str]) -> str:
        return self._encode(
            {"sub": client_id, "roles": roles, "type": "service"},
            self._service_ttl,
        )

    # ── Token verification ────────────────────────────────────────────────────

    def verify_token(self, token: str) -> dict[str, object]:
        # Step 1: Pre-check algorithm header BEFORE signature verification
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as e:
            raise AuthenticationError(
                message=f"Invalid token header: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        if header.get("alg") != "RS256":
            raise AuthenticationError(
                message=(
                    f"Rejected token with algorithm '{header.get('alg')}' — only RS256 is allowed"
                ),
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        # Step 2: Decode and verify signature using the public key
        try:
            payload: dict[str, object] = jwt.decode(token, self._public_key, algorithms=["RS256"])
        except JWTError as e:
            raise AuthenticationError(
                message=f"Invalid token: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        # Step 3: Validate required claims
        for claim in ("sub", "exp", "iat", "iss"):
            if claim not in payload:
                raise AuthenticationError(
                    message=f"Token missing required claim: '{claim}'",
                    user_message="Invalid or expired token",
                    error_code="INVALID_TOKEN",
                )

        # Step 4: Check blacklist if configured
        if self._token_blacklist is not None:
            jti = str(payload.get("jti", ""))
            if jti:
                is_blocked = self._check_blacklist(jti)
                if is_blocked:
                    raise AuthenticationError(
                        message=f"Token {jti} has been revoked",
                        user_message="Token has been revoked",
                        error_code="TOKEN_REVOKED",
                    )

        return payload

    # ── JWKS ──────────────────────────────────────────────────────────────────

    def get_jwks(self) -> dict[str, object]:
        """
        Return the public key set in JWKS format (RFC 7517).

        Consumers (other services, admin panel) fetch this endpoint to obtain
        the public key needed to verify tokens without sharing any secret.

        The 'n' and 'e' values are the RSA modulus and exponent encoded as
        base64url (no padding), as required by RFC 7518 §6.3.
        """
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        pub = load_pem_public_key(self._public_key.encode())

        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

        if not isinstance(pub, RSAPublicKey):
            raise ValueError("Public key is not an RSA key")

        pub_numbers = pub.public_numbers()

        def _b64url(n: int) -> str:
            byte_length = (n.bit_length() + 7) // 8
            return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self._key_id,
                    "n": _b64url(pub_numbers.n),
                    "e": _b64url(pub_numbers.e),
                }
            ]
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _check_blacklist(self, jti: str) -> bool:
        """Run the async is_blacklisted check from a sync context."""
        assert self._token_blacklist is not None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._token_blacklist.is_blacklisted(jti))

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, self._token_blacklist.is_blacklisted(jti)).result()

    def _encode(self, payload: dict[str, object], ttl: timedelta) -> str:
        now = datetime.now(UTC)
        expire = now + ttl
        result: str = jwt.encode(
            {
                **payload,
                "jti": str(uuid4()),
                "exp": expire,
                "iat": now,
                "iss": "ugsys-identity-manager",
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._key_id},
        )
        return result
