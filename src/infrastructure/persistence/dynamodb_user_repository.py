"""DynamoDB user repository — adapter implementing UserRepository port."""

from datetime import datetime
from typing import Any
from uuid import UUID

import aioboto3
import structlog
from boto3.dynamodb.conditions import Attr, ConditionBase
from botocore.exceptions import ClientError

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.exceptions import NotFoundError, RepositoryError
from src.domain.repositories.unit_of_work import TransactionalOperation
from src.domain.repositories.user_repository import UserRepository

logger = structlog.get_logger()


class DynamoDBUserRepository(UserRepository):
    def __init__(
        self,
        table_name: str,
        region: str = "us-east-1",
        session: aioboto3.Session | None = None,
    ) -> None:
        self._table_name = table_name
        self._region = region
        self._session = session or aioboto3.Session()

    def _raise_repository_error(self, operation: str, e: ClientError) -> None:
        logger.error(
            "dynamodb.error",
            operation=operation,
            table=self._table_name,
            error_code=e.response["Error"]["Code"],
            error=str(e),
        )
        raise RepositoryError(
            message=f"DynamoDB {operation} failed: {e}",
            user_message="An unexpected error occurred",
            error_code="REPOSITORY_ERROR",
        )

    async def save(self, user: User) -> User:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                await table.put_item(Item=self._to_item(user))
            logger.info("dynamodb.user.saved", user_id=str(user.id))
            return user
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise RepositoryError(
                    message=f"ConditionalCheckFailedException on save for user {user.id}: {e}",
                    user_message="An unexpected error occurred",
                    error_code="REPOSITORY_ERROR",
                ) from e
            self._raise_repository_error("save", e)
            raise

    async def update(self, user: User) -> User:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                await table.put_item(Item=self._to_item(user))
            logger.info("dynamodb.user.updated", user_id=str(user.id))
            return user
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFoundError(
                    message=f"User {user.id} not found for update: {e}",
                    user_message="User not found",
                    error_code="NOT_FOUND",
                ) from e
            self._raise_repository_error("update", e)
            raise

    async def find_by_id(self, user_id: UUID) -> User | None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                resp = await table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})
            item = resp.get("Item")
            return self._from_item(item) if item else None
        except ClientError as e:
            self._raise_repository_error("find_by_id", e)
            raise

    async def find_by_email(self, email: str) -> User | None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                resp = await table.query(
                    IndexName="email-index",
                    KeyConditionExpression="email = :email",
                    ExpressionAttributeValues={":email": email},
                )
            items = resp.get("Items", [])
            return self._from_item(items[0]) if items else None
        except ClientError as e:
            self._raise_repository_error("find_by_email", e)
            raise

    async def list_all(self) -> list[User]:
        try:
            items: list[dict[str, object]] = []
            kwargs: dict[str, object] = {}
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                while True:
                    resp = await table.scan(**kwargs)
                    raw = resp.get("Items", [])
                    items.extend(raw)
                    last = resp.get("LastEvaluatedKey")
                    if not last:
                        break
                    kwargs["ExclusiveStartKey"] = last
            return [self._from_item(i) for i in items if i.get("sk") == "PROFILE"]
        except ClientError as e:
            self._raise_repository_error("list_all", e)
            raise

    async def delete(self, user_id: UUID) -> None:
        try:
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                await table.delete_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})
            logger.info("dynamodb.user.deleted", user_id=str(user_id))
        except ClientError as e:
            self._raise_repository_error("delete", e)

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        role_filter: str | None = None,
    ) -> tuple[list[User], int]:
        try:
            filter_expr: ConditionBase = Attr("sk").eq("PROFILE")
            if status_filter:
                filter_expr = filter_expr & Attr("status").eq(status_filter)
            if role_filter:
                filter_expr = filter_expr & Attr("roles").contains(role_filter)

            all_items: list[dict[str, object]] = []
            kwargs: dict[str, object] = {"FilterExpression": filter_expr}
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                while True:
                    resp = await table.scan(**kwargs)
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
        except ClientError as e:
            self._raise_repository_error("list_paginated", e)
            raise

    async def find_by_verification_token(self, token: str) -> User | None:
        try:
            filter_expr = Attr("email_verification_token").eq(token) & Attr("sk").eq("PROFILE")
            async with self._session.resource("dynamodb", region_name=self._region) as dynamodb:
                table = await dynamodb.Table(self._table_name)
                resp = await table.scan(FilterExpression=filter_expr)
            items = resp.get("Items", [])
            return self._from_item(items[0]) if items else None
        except ClientError as e:
            self._raise_repository_error("find_by_verification_token", e)
            raise

    # ── Transactional operation builders ─────────────────────────────────────

    def save_operation(self, user: User) -> TransactionalOperation:
        """Return a Put TransactionalOperation for use in UnitOfWork.execute() — no I/O.

        Uses attribute_not_exists(pk) so the transaction fails if the user already exists.
        """
        return TransactionalOperation(
            operation_type="Put",
            params={
                "TableName": self._table_name,
                "Item": self._to_item_low_level(user),
                "ConditionExpression": "attribute_not_exists(pk)",
            },
        )

    def update_operation(self, user: User) -> TransactionalOperation:
        """Return a Put TransactionalOperation for use in UnitOfWork.execute() — no I/O.

        Uses attribute_exists(pk) so the transaction fails if the user does not exist.
        """
        return TransactionalOperation(
            operation_type="Put",
            params={
                "TableName": self._table_name,
                "Item": self._to_item_low_level(user),
                "ConditionExpression": "attribute_exists(pk)",
            },
        )

    def _to_item_low_level(self, user: User) -> dict[str, Any]:
        """Convert User to DynamoDB low-level AttributeValue dict.

        Required by transact_write_items which expects {"S": "..."} typed values,
        unlike the high-level resource API used by save() / update().
        """
        item: dict[str, Any] = {
            "pk": {"S": f"USER#{user.id}"},
            "sk": {"S": "PROFILE"},
            "id": {"S": str(user.id)},
            "email": {"S": user.email},
            "hashed_password": {"S": user.hashed_password},
            "full_name": {"S": user.full_name},
            "status": {"S": user.status.value},
            "roles": {"L": [{"S": r.value} for r in user.roles]},
            "created_at": {"S": user.created_at.isoformat()},
            "updated_at": {"S": user.updated_at.isoformat()},
            "failed_login_attempts": {"N": str(user.failed_login_attempts)},
            "require_password_change": {"BOOL": user.require_password_change},
            "email_verified": {"BOOL": user.email_verified},
            "is_admin": {"BOOL": user.is_admin},
        }
        # Only write optional fields when present — never store None
        if user.account_locked_until is not None:
            item["account_locked_until"] = {"S": user.account_locked_until.isoformat()}
        if user.last_login_at is not None:
            item["last_login_at"] = {"S": user.last_login_at.isoformat()}
        if user.last_password_change is not None:
            item["last_password_change"] = {"S": user.last_password_change.isoformat()}
        if user.email_verification_token is not None:
            item["email_verification_token"] = {"S": user.email_verification_token}
        if user.email_verified_at is not None:
            item["email_verified_at"] = {"S": user.email_verified_at.isoformat()}
        return item

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
