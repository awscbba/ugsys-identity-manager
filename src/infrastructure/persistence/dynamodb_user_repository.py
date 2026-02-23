"""DynamoDB user repository — adapter implementing UserRepository port."""

from datetime import datetime
from uuid import UUID

import boto3

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.repositories.user_repository import UserRepository


class DynamoDBUserRepository(UserRepository):
    def __init__(self, table_name: str, region: str = "us-east-1") -> None:
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    async def save(self, user: User) -> User:
        self._table.put_item(Item=self._to_item(user))
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

    async def delete(self, user_id: UUID) -> None:
        self._table.delete_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"})

    @staticmethod
    def _to_item(user: User) -> dict:  # type: ignore[type-arg]
        return {
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
        }

    @staticmethod
    def _from_item(item: dict) -> User:  # type: ignore[type-arg]
        return User(
            id=UUID(item["id"]),
            email=item["email"],
            hashed_password=item["hashed_password"],
            full_name=item["full_name"],
            status=UserStatus(item["status"]),
            roles=[UserRole(r) for r in item["roles"]],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
