"""JWT token service — adapter implementing TokenService port.

Uses RS256 exclusively:
  - private_key (PEM) — signs tokens
  - public_key  (PEM) — verifies tokens, exposed via JWKS endpoint
  - key_id            — included as 'kid' in JWT header and JWKS
  - retiring_public_key (PEM, optional) — verifies tokens signed with the previous key
  - retiring_key_id   (optional)        — kid for the retiring key
"""

from __future__ import annotations

import base64
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
        audience: str = "admin-panel",
        retiring_public_key: str | None = None,
        retiring_key_id: str | None = None,
    ) -> None:
        self._private_key = private_key
        self._public_key = public_key
        self._key_id = key_id
        self._token_blacklist = token_blacklist
        self._audience = audience
        self._retiring_public_key = retiring_public_key
        self._retiring_key_id = retiring_key_id
        self._access_ttl = timedelta(minutes=30)
        self._refresh_ttl = timedelta(days=7)
        self._reset_ttl = timedelta(hours=1)
        self._service_ttl = timedelta(hours=1)

    # ── Token creation ────────────────────────────────────────────────────────

    def create_access_token(self, user_id: UUID, email: str, roles: list[str]) -> str:
        return self._encode(
            {
                "sub": str(user_id),
                "email": email,
                "roles": roles,
                "type": "access",
                "aud": self._audience,
            },
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

    async def verify_token(self, token: str) -> dict[str, object]:
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

        # Step 2: Select public key by kid
        kid = header.get("kid", "")
        if kid == self._key_id:
            verify_key = self._public_key
        elif self._retiring_key_id and kid == self._retiring_key_id:
            if self._retiring_public_key is None:
                raise AuthenticationError(
                    message=f"Retiring key '{kid}' referenced but no retiring public key configured",  # noqa: E501
                    user_message="Invalid or expired token",
                    error_code="INVALID_TOKEN",
                )
            verify_key = self._retiring_public_key
        else:
            raise AuthenticationError(
                message=f"Unknown kid '{kid}' — not active key '{self._key_id}'"
                + (f" or retiring key '{self._retiring_key_id}'" if self._retiring_key_id else ""),
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        # Step 3: Decode and verify signature
        try:
            payload: dict[str, object] = jwt.decode(
                token, verify_key, algorithms=["RS256"], audience=self._audience
            )
        except JWTError as e:
            raise AuthenticationError(
                message=f"Invalid token: {e}",
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            ) from e

        # Step 4: Validate required claims
        for claim in ("sub", "exp", "iat", "iss"):
            if claim not in payload:
                raise AuthenticationError(
                    message=f"Token missing required claim: '{claim}'",
                    user_message="Invalid or expired token",
                    error_code="INVALID_TOKEN",
                )

        # Step 5: Check blacklist (async — no thread-pool workaround needed)
        if self._token_blacklist is not None:
            jti = str(payload.get("jti", ""))
            if jti:
                is_blocked = await self._token_blacklist.is_blacklisted(jti)
                if is_blocked:
                    raise AuthenticationError(
                        message=f"Token {jti} has been revoked",
                        user_message="Token has been revoked",
                        error_code="TOKEN_REVOKED",
                    )

        return payload

    # ── JWKS ──────────────────────────────────────────────────────────────────

    def get_jwks(self) -> dict[str, object]:
        """Return the public key set in JWKS format (RFC 7517).

        Includes the active key and, when configured, the retiring key so that
        consumers can verify tokens signed with either key during rotation overlap.
        """
        keys = [self._build_jwk_entry(self._public_key, self._key_id)]
        if self._retiring_public_key and self._retiring_key_id:
            keys.append(self._build_jwk_entry(self._retiring_public_key, self._retiring_key_id))
        return {"keys": keys}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_jwk_entry(self, pem: str, kid: str) -> dict[str, object]:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        pub = load_pem_public_key(pem.encode())
        if not isinstance(pub, RSAPublicKey):
            raise ValueError("Public key is not an RSA key")

        pub_numbers = pub.public_numbers()

        def _b64url(n: int) -> str:
            byte_length = (n.bit_length() + 7) // 8
            return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": _b64url(pub_numbers.n),
            "e": _b64url(pub_numbers.e),
        }

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
