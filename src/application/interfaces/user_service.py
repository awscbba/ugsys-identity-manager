"""IUserService — inbound port interface for the user application service.

Imports only from domain and application layers — never from infrastructure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
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
    from src.application.queries.get_user import GetUserQuery
    from src.application.queries.list_users import ListUsersQuery
    from src.domain.entities.user import User, UserRole


class IUserService(ABC):
    """Inbound port — defines the contract for the user application service."""

    @abstractmethod
    async def get_user(self, query: GetUserQuery) -> User: ...

    @abstractmethod
    async def update_profile(self, command: UpdateProfileCommand) -> User: ...

    @abstractmethod
    async def assign_role(self, command: AssignRoleCommand) -> User: ...

    @abstractmethod
    async def remove_role(self, command: RemoveRoleCommand) -> User: ...

    @abstractmethod
    async def deactivate(self, command: DeactivateUserCommand) -> User: ...

    @abstractmethod
    async def suspend_user(self, cmd: SuspendUserCommand) -> User: ...

    @abstractmethod
    async def activate_user(self, cmd: ActivateUserCommand) -> User: ...

    @abstractmethod
    async def require_password_change(self, cmd: RequirePasswordChangeCommand) -> User: ...

    @abstractmethod
    async def list_users(self, query: ListUsersQuery) -> tuple[list[User], int]: ...

    @abstractmethod
    async def get_user_roles(
        self, user_id: UUID, requester_id: str, is_admin: bool
    ) -> list[UserRole]: ...
