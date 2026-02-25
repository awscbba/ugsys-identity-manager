"""DynamoDB user repository — adapter implementing UserRepository port."""

from datetime import datetime
from uuid import UUID

import boto3
import structlog
from boto3.dynamodb.conditions import Attr

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class DynamoDBUserRepository(UserRepository):
    def __init__(self, table_name: str, region: str = "us-east-1") -> None:
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    async def save(self, user: User) -> User:
        self._table.put_item(Item=self._to_item(user))
        logger.info("dynamodb.user.saved", user_id=str(user.id))
        return user

    async def update(self, user: User) -> User:
        self._table.put_item(Item=self._to_item(user))
        logger.info("dynamodb.user.updated", user_id=str(user.id))
        return user

    async def find_by_id(self, user_id: UUID) -> User | None:
        resp = self._table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})
        item = resp.get("Item")
        return self._from_item(item) if item else None

    async def find_by_email(self, email: str) -> User | None:
        resp = self._table.query(
            IndexName="email-index",
            KeyConditionExpression="email = :email",
            ExpressionAttributeValues={":email": email},
        )
        items = resp.get("Items", [])
        return self._from_item(items[0]) if items else None

    async def list_all(self) -> list[User]:
        items: list[dict] = []  # type: ignore[type-arg]
        kwargs: dict[str, object] = {}
        while True:
            resp = self._table.scan(**kwargs)  # type: ignore[arg-type]
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return [self._from_item(i) for i in items if i.get("sk") == "PROFILE"]

    async def delete(self, user_id: UUID) -> None:
        self._table.delete_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})
        logger.info("dynamodb.user.deleted", user_id=str(user_id))

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        role_filter: str | None = None,
    ) -> tuple[list[User], int]:
        """Return (users_page, total_count) with optional filters."""
        filter_expr = Attr("sk").eq("PROFILE")

        if status_filter:
            filter_expr = filter_expr & Attr("status").eq(status_filter)

        if role_filter:
            filter_expr = filter_expr & Attr("roles").contains(role_filter)

        all_items: list[dict] = []  # type: ignore[type-arg]
        kwargs: dict[str, object] = {"FilterExpression": filter_expr}
        while True:
            resp = self._table.scan(**kwargs)  # type: ignore[arg-type]
            all_items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        total_count = len(all_items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = all_items[start:end]

        return [self._from_item(i) for i in page_items], total_count

    async def find_by_verification_token(self, token: str) -> User | None:
        """Find a user by their email verification token."""
        filter_expr = Attr("email_verification_token").eq(token) & Attr("sk").eq("PROFILE")
        resp = self._table.scan(FilterExpression=filter_expr)
        items = resp.get("Items", [])
        return self._from_item(items[0]) if items else None

    @staticmethod
    def _to_item(user: User) -> dict:  # type: ignore[type-arg]
        item: dict[str, object] = {
            "pk": f"USER#{user.id}",
            "sk": "PROFILE",
            "id": str(user.id),
            "email": user.email,
            "hashed_password": user.hashed_password,
            "full_name": user.full_name,
            "status": user.status.value,
            "roles": [r.value for r in user.roles],
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
            # Security fields
            "failed_login_attempts": user.failed_login_attempts,
            "require_password_change": user.require_password_change,
            # Verification fields
            "email_verified": user.email_verified,
            # Legacy compatibility
            "is_admin": user.is_admin,
        }

        # Only include non-None datetime fields — don't write None to DynamoDB
        if user.account_locked_until is not None:
            item["account_locked_until"] = user.account_locked_until.isoformat()
        if user.last_login_at is not None:
            item["last_login_at"] = user.last_login_at.isoformat()
        if user.last_password_change is not None:
            item["last_password_change"] = user.last_password_change.isoformat()
        if user.email_verification_token is not None:
            item["email_verification_token"] = user.email_verification_token
        if user.email_verified_at is not None:
            item["email_verified_at"] = user.email_verified_at.isoformat()

        return item

    @staticmethod
    def _from_item(item: dict) -> User:  # type: ignore[type-arg]
        status_val = item.get("status", "active")
        status = UserStatus(status_val)

        return User(
            id=UUID(item["id"]),
            email=item["email"],
            hashed_password=item["hashed_password"],
            full_name=item["full_name"],
            status=status,
            roles=[UserRole(r) for r in item.get("roles", ["member"])],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            # Security fields — backward compatible defaults
            failed_login_attempts=int(item.get("failed_login_attempts", 0)),
            account_locked_until=(
                datetime.fromisoformat(item["account_locked_until"])
                if item.get("account_locked_until")
                else None
            ),
            last_login_at=(
                datetime.fromisoformat(item["last_login_at"]) if item.get("last_login_at") else None
            ),
            last_password_change=(
                datetime.fromisoformat(item["last_password_change"])
                if item.get("last_password_change")
                else None
            ),
            require_password_change=bool(item.get("require_password_change", False)),
            # Verification fields — backward compatible defaults
            email_verified=bool(
                item.get(
                    "email_verified",
                    status_val == "active",  # legacy: assume active users are verified
                )
            ),
            email_verification_token=item.get("email_verification_token"),
            email_verified_at=(
                datetime.fromisoformat(item["email_verified_at"])
                if item.get("email_verified_at")
                else None
            ),
            # Legacy compatibility
            is_admin=bool(item.get("is_admin", False)),
        )
