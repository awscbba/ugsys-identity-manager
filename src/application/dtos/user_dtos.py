"""User request/response DTOs — extracted from presentation layer.

These live in the application layer so they can be referenced by
IUserService and tested independently of FastAPI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.domain.entities.user import UserRole

if TYPE_CHECKING:
    from src.domain.entities.user import User


class UpdateProfileRequest(BaseModel):
    full_name: str


class AssignRoleRequest(BaseModel):
    role: UserRole


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    status: str
    roles: list[str]

    @classmethod
    def from_domain(cls, user: User) -> UserResponse:
        return cls(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            status=user.status.value,
            roles=[r.value for r in user.roles],
        )


class PaginatedUsersResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
