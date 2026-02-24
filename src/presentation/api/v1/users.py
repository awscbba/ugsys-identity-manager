"""Users router — /api/v1/users endpoints."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.application.queries.get_user import GetUserQuery
from src.application.services.user_service import UserService
from src.domain.repositories.token_service import TokenService

logger = structlog.get_logger()
router = APIRouter(prefix="/users", tags=["users"])
bearer = HTTPBearer()


class UserResponse(dict):  # type: ignore[type-arg]
    pass


def get_user_service() -> UserService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("UserService not wired")


def get_token_service() -> TokenService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("TokenService not wired")


def _extract_claims(
    credentials: HTTPAuthorizationCredentials,
    token_service: TokenService,
) -> dict:  # type: ignore[type-arg]
    try:
        return token_service.verify_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


@router.get("/me")
async def get_me(
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    user_id = UUID(str(claims["sub"]))
    try:
        user = await user_service.get_user(
            GetUserQuery(user_id=user_id, requester_id=str(user_id), is_admin=False)
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status.value,
        "roles": [r.value for r in user.roles],
    }


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    roles: list[str] = list(claims.get("roles", []))
    is_admin = "admin" in roles or "super_admin" in roles
    try:
        user = await user_service.get_user(
            GetUserQuery(user_id=user_id, requester_id=requester_id, is_admin=is_admin)
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status.value,
        "roles": [r.value for r in user.roles],
    }
