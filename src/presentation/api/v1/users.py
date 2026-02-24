"""Users router — /api/v1/users endpoints."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.application.commands.update_user import (
    AssignRoleCommand,
    DeactivateUserCommand,
    RemoveRoleCommand,
    UpdateProfileCommand,
)
from src.application.queries.get_user import GetUserQuery
from src.application.services.user_service import UserService
from src.domain.entities.user import UserRole
from src.domain.repositories.token_service import TokenService

logger = structlog.get_logger()
router = APIRouter(prefix="/users", tags=["users"])
bearer = HTTPBearer()


class UpdateProfileRequest(BaseModel):
    full_name: str


class AssignRoleRequest(BaseModel):
    role: UserRole


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


def _require_admin(claims: dict) -> None:  # type: ignore[type-arg]
    roles: list[str] = list(claims.get("roles", []))
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def _user_dict(user: object) -> dict:  # type: ignore[type-arg]
    from src.domain.entities.user import User

    u: User = user  # type: ignore[assignment]
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "status": u.status.value,
        "roles": [r.value for r in u.roles],
    }


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
    return _user_dict(user)


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
    return _user_dict(user)


@router.patch("/{user_id}")
async def update_profile(
    user_id: UUID,
    body: UpdateProfileRequest,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    try:
        user = await user_service.update_profile(
            UpdateProfileCommand(
                user_id=user_id,
                requester_id=requester_id,
                full_name=body.full_name,
            )
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return _user_dict(user)


@router.put("/{user_id}/roles/{role}")
async def assign_role(
    user_id: UUID,
    role: UserRole,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    _require_admin(claims)
    try:
        user = await user_service.assign_role(
            AssignRoleCommand(user_id=user_id, role=role, requester_id=str(claims["sub"]))
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return _user_dict(user)


@router.delete("/{user_id}/roles/{role}", status_code=status.HTTP_200_OK)
async def remove_role(
    user_id: UUID,
    role: UserRole,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    _require_admin(claims)
    try:
        user = await user_service.remove_role(
            RemoveRoleCommand(user_id=user_id, role=role, requester_id=str(claims["sub"]))
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return _user_dict(user)


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: UserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    _require_admin(claims)
    try:
        user = await user_service.deactivate(
            DeactivateUserCommand(user_id=user_id, requester_id=str(claims["sub"]))
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    return _user_dict(user)
