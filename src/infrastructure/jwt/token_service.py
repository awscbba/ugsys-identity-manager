"""JWT token service — adapter implementing TokenService port."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt

from src.domain.ports.token_service import TokenService


class JWTTokenService(TokenService):
    def __init__(self, secret_key: str, algorithm: str = "HS256") -> None:
        self._secret = secret_key
        self._algorithm = algorithm
        self._access_ttl = timedelta(minutes=30)
        self._refresh_ttl = timedelta(days=7)

    def create_access_token(self, user_id: UUID, roles: list[str]) -> str:
        return self._encode(
            {"sub": str(user_id), "roles": roles, "type": "access"},
            self._access_ttl,
        )

    def create_refresh_token(self, user_id: UUID) -> str:
        return self._encode({"sub": str(user_id), "type": "refresh"}, self._refresh_ttl)

    def verify_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}") from e

    def _encode(self, payload: dict, ttl: timedelta) -> str:
        expire = datetime.now(UTC) + ttl
        return jwt.encode({**payload, "exp": expire}, self._secret, algorithm=self._algorithm)
