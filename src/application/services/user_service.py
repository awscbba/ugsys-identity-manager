"""User application service — orchestrates user read/update/admin use cases."""

import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

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
from src.application.interfaces.user_service import IUserService
from src.application.queries.get_user import GetUserQuery
from src.application.queries.list_users import ListUsersQuery
from src.domain.entities.outbox_event import OutboxEvent
from src.domain.entities.user import User, UserRole
from src.domain.exceptions import AuthorizationError, NotFoundError
from src.domain.repositories.event_publisher import EventPublisher
from src.domain.repositories.outbox_repository import OutboxRepository
from src.domain.repositories.unit_of_work import UnitOfWork
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class UserService(IUserService):
    def __init__(
        self,
        user_repo: UserRepository,
        event_publisher: EventPublisher | None = None,
        outbox_repo: OutboxRepository | None = None,
        unit_of_work: UnitOfWork | None = None,
    ) -> None:
        self._user_repo = user_repo
        self._events = event_publisher
        self._outbox_repo = outbox_repo
        self._unit_of_work = unit_of_work

    async def _verify_admin(self, admin_id: str) -> User:
        """Look up admin user and verify they have admin or super_admin role."""
        admin = await self._user_repo.find_by_id(UUID(admin_id))
        is_admin = admin is not None and (
            admin.has_role(UserRole.ADMIN) or admin.has_role(UserRole.SUPER_ADMIN)
        )
        if not admin or not is_admin:
            raise AuthorizationError(
                message=f"User {admin_id} is not an admin",
                user_message="Access denied",
                error_code="FORBIDDEN",
            )
        return admin

    async def get_user(self, query: GetUserQuery) -> User:
        start = time.perf_counter()
        logger.info("user_service.get_user.started", user_id=str(query.user_id))
        user = await self._user_repo.find_by_id(query.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {query.user_id}",
                user_message="User not found",
            )
        # IDOR check — non-admins can only access their own profile
        if not query.is_admin and str(user.id) != query.requester_id:
            logger.warning(
                "user_service.get_user.forbidden",
                requester=query.requester_id,
                target=str(query.user_id),
            )
            raise AuthorizationError(
                message=f"User {query.requester_id} attempted IDOR on {query.user_id}",
                user_message="Access denied",
                error_code="FORBIDDEN",
            )
        logger.info(
            "user_service.get_user.completed",
            user_id=str(user.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return user

    async def update_profile(self, command: UpdateProfileCommand) -> User:
        start = time.perf_counter()
        logger.info("user_service.update_profile.started", user_id=str(command.user_id))
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {command.user_id}",
                user_message="User not found",
            )
        # Only self or admin can update profile
        if str(user.id) != command.requester_id:
            raise AuthorizationError(
                message=f"User {command.requester_id} attempted IDOR on {command.user_id}",
                user_message="Access denied",
                error_code="FORBIDDEN",
            )
        user.update_profile(command.full_name)
        updated = await self._user_repo.update(user)
        if self._events:
            await self._events.publish(
                detail_type="identity.user.updated",
                payload={"user_id": str(updated.id)},
            )
        logger.info(
            "user_service.update_profile.completed",
            user_id=str(updated.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def assign_role(self, command: AssignRoleCommand) -> User:
        start = time.perf_counter()
        logger.info(
            "user_service.assign_role.started",
            user_id=str(command.user_id),
            role=command.role,
        )
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {command.user_id}",
                user_message="User not found",
            )
        user.assign_role(command.role)
        updated = await self._user_repo.update(user)
        if self._events:
            await self._events.publish(
                detail_type="identity.user.role_changed",
                payload={
                    "user_id": str(updated.id),
                    "email": updated.email,
                    "role": command.role,
                    "action": "assigned",
                },
            )
        logger.info(
            "user_service.assign_role.completed",
            user_id=str(updated.id),
            role=command.role,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def remove_role(self, command: RemoveRoleCommand) -> User:
        start = time.perf_counter()
        logger.info(
            "user_service.remove_role.started",
            user_id=str(command.user_id),
            role=command.role,
        )
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {command.user_id}",
                user_message="User not found",
            )
        user.remove_role(command.role)
        updated = await self._user_repo.update(user)
        if self._events:
            await self._events.publish(
                detail_type="identity.user.role_changed",
                payload={
                    "user_id": str(updated.id),
                    "email": updated.email,
                    "role": command.role,
                    "action": "removed",
                },
            )
        logger.info(
            "user_service.remove_role.completed",
            user_id=str(updated.id),
            role=command.role,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def deactivate(self, command: DeactivateUserCommand) -> User:
        start = time.perf_counter()
        logger.info("user_service.deactivate.started", user_id=str(command.user_id))
        user = await self._user_repo.find_by_id(command.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {command.user_id}",
                user_message="User not found",
            )
        user.deactivate()

        if self._outbox_repo and self._unit_of_work:
            outbox_event = OutboxEvent(
                id=str(uuid4()),
                aggregate_type="User",
                aggregate_id=str(user.id),
                event_type="identity.user.deactivated",
                payload=json.dumps({"user_id": str(user.id), "email": user.email}),
                created_at=datetime.now(UTC).isoformat(),
                status="pending",
            )
            await self._unit_of_work.execute(
                [
                    self._user_repo.update_operation(user),
                    self._outbox_repo.save_operation(outbox_event),
                ]
            )
            updated = user
        else:
            updated = await self._user_repo.update(user)
            if self._events:
                await self._events.publish(
                    detail_type="identity.user.deactivated",
                    payload={"user_id": str(updated.id), "email": updated.email},
                )

        logger.info(
            "user_service.deactivate.completed",
            user_id=str(updated.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def suspend_user(self, cmd: SuspendUserCommand) -> User:
        """Suspend a user account (admin only)."""
        start = time.perf_counter()
        logger.info(
            "user_service.suspend_user.started",
            user_id=str(cmd.user_id),
            admin_id=cmd.admin_id,
        )
        await self._verify_admin(cmd.admin_id)
        user = await self._user_repo.find_by_id(cmd.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {cmd.user_id}",
                user_message="User not found",
            )
        user.deactivate()
        updated = await self._user_repo.update(user)
        if self._events:
            await self._events.publish(
                detail_type="identity.user.deactivated",
                payload={"user_id": str(updated.id), "email": updated.email},
            )
        logger.info(
            "user_service.suspend_user.completed",
            user_id=str(updated.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def activate_user(self, cmd: ActivateUserCommand) -> User:
        """Activate a user account (admin only)."""
        start = time.perf_counter()
        logger.info(
            "user_service.activate_user.started",
            user_id=str(cmd.user_id),
            admin_id=cmd.admin_id,
        )
        await self._verify_admin(cmd.admin_id)
        user = await self._user_repo.find_by_id(cmd.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {cmd.user_id}",
                user_message="User not found",
            )
        user.activate()
        updated = await self._user_repo.update(user)
        if self._events:
            await self._events.publish(
                detail_type="identity.user.activated",
                payload={"user_id": str(updated.id), "email": updated.email},
            )
        logger.info(
            "user_service.activate_user.completed",
            user_id=str(updated.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def require_password_change(self, cmd: RequirePasswordChangeCommand) -> User:
        """Force a user to change their password (admin only)."""
        start = time.perf_counter()
        logger.info(
            "user_service.require_password_change.started",
            user_id=str(cmd.user_id),
            admin_id=cmd.admin_id,
        )
        await self._verify_admin(cmd.admin_id)
        user = await self._user_repo.find_by_id(cmd.user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {cmd.user_id}",
                user_message="User not found",
            )
        user.require_password_change = True
        user.updated_at = datetime.now(UTC)
        updated = await self._user_repo.update(user)
        logger.info(
            "user_service.require_password_change.completed",
            user_id=str(updated.id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return updated

    async def list_users(self, query: ListUsersQuery) -> tuple[list[User], int]:
        """List users with pagination — admin only."""
        start = time.perf_counter()
        logger.info(
            "user_service.list_users.started",
            admin_id=query.admin_id,
            page=query.page,
            page_size=query.page_size,
        )
        await self._verify_admin(query.admin_id)
        page_size = min(query.page_size, 100)
        users, total = await self._user_repo.list_paginated(
            page=query.page,
            page_size=page_size,
            status_filter=query.status_filter,
            role_filter=query.role_filter,
        )
        logger.info(
            "user_service.list_users.completed",
            count=len(users),
            total=total,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return users, total

    async def get_user_roles(
        self, user_id: UUID, requester_id: str, is_admin: bool
    ) -> list[UserRole]:
        """Return the roles for a user. Admins can query any user; users can query themselves."""
        start = time.perf_counter()
        user = await self._user_repo.find_by_id(user_id)
        if not user:
            raise NotFoundError(
                message=f"User not found: {user_id}",
                user_message="User not found",
            )
        if not is_admin and str(user.id) != requester_id:
            raise AuthorizationError(
                message=f"User {requester_id} attempted IDOR on {user_id}",
                user_message="Access denied",
                error_code="FORBIDDEN",
            )
        logger.info(
            "user_service.get_user_roles.completed",
            user_id=str(user_id),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return list(user.roles)
