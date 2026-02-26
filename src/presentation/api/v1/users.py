"""Users router — /api/v1/users endpoints."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.application.commands.admin_user import (
    ActivateUserCommand,
    RequirePasswordChangeCommand,
    SuspendUserCommand,
)
from src.application.commands.update_user import (
    AssignRoleCommand,
    DeactivateUserCommand,
    RemoveRoleCommand,
    UpdateProfileCommand,
)
from src.application.dtos.user_dtos import UpdateProfileRequest
from src.application.interfaces.user_service import IUserService
from src.application.queries.get_user import GetUserQuery
from src.application.queries.list_users import ListUsersQuery
from src.domain.entities.user import UserRole
from src.domain.repositories.token_service import TokenService
from src.presentation.middleware.correlation_id import correlation_id_var
from src.presentation.response_envelope import list_response, success_response

logger = structlog.get_logger()
router = APIRouter(prefix="/users", tags=["users"])
bearer = HTTPBearer()


def get_user_service() -> IUserService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("UserService not wired")


def get_token_service() -> TokenService:  # pragma: no cover
    """Dependency — overridden in main.py via app.dependency_overrides."""
    raise NotImplementedError("TokenService not wired")


def _extract_claims(
    credentials: HTTPAuthorizationCredentials,
    token_service: TokenService,
) -> dict:  # type: ignore[type-arg]
    """Extract and verify JWT claims. Domain exceptions propagate to exception_handler."""
    return token_service.verify_token(credentials.credentials)


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


# ── List users (admin, paginated) ────────────────────────────────────────────


@router.get("")
async def list_users(
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    role: str | None = None,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    query = ListUsersQuery(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        role_filter=role,
        admin_id=requester_id,
    )
    users, total = await user_service.list_users(query)
    users_data: list[object] = [_user_dict(u) for u in users]
    request_id = correlation_id_var.get("")
    return list_response(users_data, total, page, page_size, request_id)


# ── Get current user ─────────────────────────────────────────────────────────


@router.get("/me")
async def get_me(
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    user_id = UUID(str(claims["sub"]))
    user = await user_service.get_user(
        GetUserQuery(user_id=user_id, requester_id=str(user_id), is_admin=False)
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


# ── Get user by ID ───────────────────────────────────────────────────────────


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    roles: list[str] = list(claims.get("roles", []))
    is_admin = "admin" in roles or "super_admin" in roles
    user = await user_service.get_user(
        GetUserQuery(user_id=user_id, requester_id=requester_id, is_admin=is_admin)
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


# ── Update profile ───────────────────────────────────────────────────────────


@router.patch("/{user_id}")
async def update_profile(
    user_id: UUID,
    body: UpdateProfileRequest,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    user = await user_service.update_profile(
        UpdateProfileCommand(
            user_id=user_id,
            requester_id=requester_id,
            full_name=body.full_name,
        )
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


# ── Role management ──────────────────────────────────────────────────────────


@router.put("/{user_id}/roles/{role}")
async def assign_role(
    user_id: UUID,
    role: UserRole,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    user = await user_service.assign_role(
        AssignRoleCommand(user_id=user_id, role=role, requester_id=str(claims["sub"]))
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


@router.delete("/{user_id}/roles/{role}", status_code=status.HTTP_200_OK)
async def remove_role(
    user_id: UUID,
    role: UserRole,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    user = await user_service.remove_role(
        RemoveRoleCommand(user_id=user_id, role=role, requester_id=str(claims["sub"]))
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


@router.get("/{user_id}/roles")
async def get_user_roles(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    roles: list[str] = list(claims.get("roles", []))
    is_admin = "admin" in roles or "super_admin" in roles
    user_roles = await user_service.get_user_roles(
        user_id=user_id, requester_id=requester_id, is_admin=is_admin
    )
    request_id = correlation_id_var.get("")
    return success_response(
        {"user_id": str(user_id), "roles": [r.value for r in user_roles]}, request_id
    )


# ── Deactivate user ──────────────────────────────────────────────────────────


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    user = await user_service.deactivate(
        DeactivateUserCommand(user_id=user_id, requester_id=str(claims["sub"]))
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


# ── Admin operations ─────────────────────────────────────────────────────────


@router.post("/{user_id}/suspend")
async def suspend_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    user = await user_service.suspend_user(
        SuspendUserCommand(user_id=user_id, admin_id=requester_id)
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    user = await user_service.activate_user(
        ActivateUserCommand(user_id=user_id, admin_id=requester_id)
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)


@router.post("/{user_id}/require-password-change")
async def require_password_change(
    user_id: UUID,
    credentials: HTTPAuthorizationCredentials = Security(bearer),  # noqa: B008
    user_service: IUserService = Depends(get_user_service),  # noqa: B008
    token_service: TokenService = Depends(get_token_service),  # noqa: B008
) -> dict:  # type: ignore[type-arg]
    claims = _extract_claims(credentials, token_service)
    requester_id = str(claims["sub"])
    user = await user_service.require_password_change(
        RequirePasswordChangeCommand(user_id=user_id, admin_id=requester_id)
    )
    request_id = correlation_id_var.get("")
    return success_response(_user_dict(user), request_id)
