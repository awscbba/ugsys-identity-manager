"""Commands for user management use cases."""

from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.user import UserRole


@dataclass(frozen=True)
class UpdateProfileCommand:
    user_id: UUID
    requester_id: str
    full_name: str


@dataclass(frozen=True)
class AssignRoleCommand:
    user_id: UUID
    role: UserRole
    requester_id: str  # must be admin/super_admin


@dataclass(frozen=True)
class RemoveRoleCommand:
    user_id: UUID
    role: UserRole
    requester_id: str  # must be admin/super_admin


@dataclass(frozen=True)
class DeactivateUserCommand:
    user_id: UUID
    requester_id: str  # must be admin/super_admin
