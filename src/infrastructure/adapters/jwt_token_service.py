"""JWT token service — adapter implementing TokenService port.

NOTE: Uses RS256 in production. HS256 is kept here only for local dev convenience;
the algorithm is injected via config so prod always passes RS256.
"""

from __future__ import annotations

import asyncio
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
        secret_key: str,
        algorithm: str = "RS256",
        token_blacklist: TokenBlacklistRepository | None = None,
    ) -> None:
        self._secret = secret_key
        self._algorithm = algorithm
        self._token_blacklist = token_blacklist
        self._access_ttl = timedelta(minutes=30)
        self._refresh_ttl = timedelta(days=7)
        self._reset_ttl = timedelta(hours=1)
        self._service_ttl = timedelta(hours=1)

    def create_access_token(self, user_id: UUID, roles: list[str]) -> str:
        return self._encode(
            {"sub": str(user_id), "roles": roles, "type": "access"},
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

        if header.get("alg") not in ("RS256",):
            raise AuthenticationError(
                message=(
                    f"Rejected token with algorithm '{header.get('alg')}' — only RS256 is allowed"
                ),
                user_message="Invalid or expired token",
                error_code="INVALID_TOKEN",
            )

        # Step 2: Decode and verify signature
        try:
            payload: dict[str, object] = jwt.decode(token, self._secret, algorithms=["RS256"])
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

    def _check_blacklist(self, jti: str) -> bool:
        """Run the async is_blacklisted check from a sync context."""
        assert self._token_blacklist is not None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(self._token_blacklist.is_blacklisted(jti))

        # Already inside an async loop (e.g. FastAPI request) — run in a thread
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
            self._secret,
            algorithm=self._algorithm,
        )
        return result
