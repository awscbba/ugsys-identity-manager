"""JWT token service — adapter implementing TokenService port.

NOTE: Uses RS256 in production. HS256 is kept here only for local dev convenience;
the algorithm is injected via config so prod always passes RS256.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt

from src.domain.repositories.token_service import TokenService


class JWTTokenService(TokenService):
    def __init__(self, secret_key: str, algorithm: str = "RS256") -> None:
        self._secret = secret_key
        self._algorithm = algorithm
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
        try:
            payload: dict[str, object] = jwt.decode(
                token, self._secret, algorithms=[self._algorithm]
            )
            if payload.get("alg") == "none" or self._algorithm == "none":
                raise ValueError("Algorithm 'none' is not allowed")
            return payload
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}") from e

    def _encode(self, payload: dict[str, object], ttl: timedelta) -> str:
        expire = datetime.now(UTC) + ttl
        result: str = jwt.encode(
            {**payload, "exp": expire}, self._secret, algorithm=self._algorithm
        )
        return result
