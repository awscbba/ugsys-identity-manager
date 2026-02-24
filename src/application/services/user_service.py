"""User application service — orchestrates user read/update/admin use cases."""

from typing import Protocol
from uuid import UUID

import structlog

from src.application.commands.update_user import (
    AssignRoleCommand,
    DeactivateUserCommand,
    RemoveRoleCommand,
    UpdateProfileCommand,
)
from src.application.queries.get_user import GetUserQuery
from src.domain.entities.user import User, UserRole
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class EventPublisherProtocol(Protocol):
    def publish(self, source: str, detail_type: str, detail: dict) -> None:  # type: ignore[type-arg]
        ...


class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        event_publisher: EventPublisherProtocol | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._events = event_publisher

    async def get_user(self, query: GetUserQuery) -> User:
        logger.info("user_service.get_user.started", user_id=str(query.user_id))
        user = await self._user_repo.find_by_id(query.user_id)
        if not user:
            raise ValueError(f"User not found: {query.user_id}")
        # IDOR check — non-admins can only access their own profile
        if not query.is_admin and str(user.id) != query.requester_id:
            logger.warning(
                "user_service.get_user.forbidden",
                requester=query.requester_id,
                target=str(query.user_id),
            )
            raise PermissionError("Access denied")
        logger.info("user_service.get_user.completed", user_id=str(user.id))
        return user

    async def update_profile(self, command: UpdateProfileCommand) -> User:
        logger.info("user_service.update_profile.started", user_id=str(command.user_id))
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise ValueError(f"User not found: {command.user_id}")
        # Only self or admin can update profile
        if str(user.id) != command.requester_id:
            raise PermissionError("Access denied")
        user.update_profile(command.full_name)
        updated = await self._user_repo.update(user)
        logger.info("user_service.update_profile.completed", user_id=str(updated.id))
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.user.updated",
                detail={"user_id": str(updated.id)},
            )
        return updated

    async def assign_role(self, command: AssignRoleCommand) -> User:
        logger.info(
            "user_service.assign_role.started",
            user_id=str(command.user_id),
            role=command.role,
        )
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise ValueError(f"User not found: {command.user_id}")
        user.assign_role(command.role)
        updated = await self._user_repo.update(user)
        logger.info(
            "user_service.assign_role.completed", user_id=str(updated.id), role=command.role
        )
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.user.role_changed",
                detail={"user_id": str(updated.id), "role": command.role, "action": "assigned"},
            )
        return updated

    async def remove_role(self, command: RemoveRoleCommand) -> User:
        logger.info(
            "user_service.remove_role.started",
            user_id=str(command.user_id),
            role=command.role,
        )
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise ValueError(f"User not found: {command.user_id}")
        user.remove_role(command.role)
        updated = await self._user_repo.update(user)
        logger.info(
            "user_service.remove_role.completed", user_id=str(updated.id), role=command.role
        )
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.user.role_changed",
                detail={"user_id": str(updated.id), "role": command.role, "action": "removed"},
            )
        return updated

    async def deactivate(self, command: DeactivateUserCommand) -> User:
        logger.info("user_service.deactivate.started", user_id=str(command.user_id))
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise ValueError(f"User not found: {command.user_id}")
        user.deactivate()
        updated = await self._user_repo.update(user)
        logger.info("user_service.deactivate.completed", user_id=str(updated.id))
        if self._events:
            self._events.publish(
                source="ugsys.identity-manager",
                detail_type="identity.user.deleted",
                detail={"user_id": str(updated.id)},
            )
        return updated

    async def list_users(self, requester_id: str, is_admin: bool) -> list[User]:
        """List all users — admin only."""
        if not is_admin:
            raise PermissionError("Admin access required")
        logger.info("user_service.list_users.started", requester=requester_id)
        users = await self._user_repo.list_all()
        logger.info("user_service.list_users.completed", count=len(users))
        return users

    async def get_user_roles(
        self, user_id: UUID, requester_id: str, is_admin: bool
    ) -> list[UserRole]:
        """Return the roles for a user. Admins can query any user; users can query themselves."""
        user = await self._user_repo.find_by_id(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
        if not is_admin and str(user.id) != requester_id:
            raise PermissionError("Access denied")
        return list(user.roles)
