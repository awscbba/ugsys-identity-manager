"""Roles router — /api/v1/roles endpoints."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domain.entities.user import UserRole
from src.domain.repositories.token_service import TokenService

logger = structlog.get_logger()
router = APIRouter(prefix="/roles", tags=["roles"])
bearer = HTTPBearer()


def get_token_service() -> TokenService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("TokenService not wired")


def _require_admin(credentials: HTTPAuthorizationCredentials, token_service: TokenService) -> None:
    try:
        payload = token_service.verify_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    roles: list[str] = list(payload.get("roles", []))  # type: ignore[arg-type]
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.get("")
async def list_roles(
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    """List all available roles in the system."""
    _require_admin(credentials, token_service)
    roles = [{"name": r.value, "description": _role_description(r)} for r in UserRole]
    logger.info("roles.list.success", count=len(roles))
    return {"roles": roles}


def _role_description(role: UserRole) -> str:
    descriptions = {
        UserRole.SUPER_ADMIN: "Full platform access — can manage admins and all resources",
        UserRole.ADMIN: "Administrative access — can manage users and content",
        UserRole.MEMBER: "Standard member — access to community features",
    }
    return descriptions.get(role, "")
