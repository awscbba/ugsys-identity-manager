"""User application service — orchestrates user read/update use cases."""

import structlog

from src.application.queries.get_user import GetUserQuery
from src.domain.entities.user import User
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class UserService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

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
