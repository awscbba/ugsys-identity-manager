"""Admin user management command DTOs."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class SuspendUserCommand:
    """Command to suspend a user account (admin only)."""

    user_id: UUID
    admin_id: str


@dataclass(frozen=True)
class ActivateUserCommand:
    """Command to activate a user account (admin only)."""

    user_id: UUID
    admin_id: str


@dataclass(frozen=True)
class RequirePasswordChangeCommand:
    """Command to force a user to change their password (admin only)."""

    user_id: UUID
    admin_id: str
