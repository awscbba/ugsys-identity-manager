"""Unit tests for DynamoDBUserRepository transactional operation methods.

TDD: RED phase — tests written before implementation.
Covers save_operation(), update_operation(), and _to_item_low_level().
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from src.domain.entities.user import User, UserRole, UserStatus
from src.domain.repositories.unit_of_work import TransactionalOperation
from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_user(
    *,
    email: str = "dev@example.com",
    full_name: str = "Dev User",
    hashed_password: str = "hashed",  # noqa: S107
    status: UserStatus = UserStatus.ACTIVE,
    roles: list[UserRole] | None = None,
    email_verified: bool = True,
) -> User:
    return User(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        status=status,
        roles=roles or [UserRole.MEMBER],
        created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC),
        email_verified=email_verified,
    )


def make_repo() -> DynamoDBUserRepository:
    repo = DynamoDBUserRepository.__new__(DynamoDBUserRepository)
    repo._table_name = "ugsys-users-test"
    repo._region = "us-east-1"
    repo._session = MagicMock()
    return repo


# ── _to_item_low_level() ──────────────────────────────────────────────────────


class TestToItemLowLevel:
    """_to_item_low_level() must produce DynamoDB AttributeValue dict format."""

    def test_pk_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user()
        item = repo._to_item_low_level(user)

        assert item["pk"] == {"S": f"USER#{user.id}"}

    def test_sk_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user()
        item = repo._to_item_low_level(user)

        assert item["sk"] == {"S": "PROFILE"}

    def test_id_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user()
        item = repo._to_item_low_level(user)

        assert item["id"] == {"S": str(user.id)}

    def test_email_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user(email="test@example.com")
        item = repo._to_item_low_level(user)

        assert item["email"] == {"S": "test@example.com"}

    def test_full_name_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user(full_name="Test User")
        item = repo._to_item_low_level(user)

        assert item["full_name"] == {"S": "Test User"}

    def test_status_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user(status=UserStatus.ACTIVE)
        item = repo._to_item_low_level(user)

        assert item["status"] == {"S": "active"}

    def test_roles_is_attribute_value_list_of_strings(self) -> None:

        repo = make_repo()
        user = make_user(roles=[UserRole.MEMBER, UserRole.ADMIN])
        item = repo._to_item_low_level(user)

        assert item["roles"] == {"L": [{"S": "member"}, {"S": "admin"}]}

    def test_email_verified_is_attribute_value_bool(self) -> None:

        repo = make_repo()
        user = make_user(email_verified=True)
        item = repo._to_item_low_level(user)

        assert item["email_verified"] == {"BOOL": True}

    def test_failed_login_attempts_is_attribute_value_number(self) -> None:

        repo = make_repo()
        user = make_user()
        user.failed_login_attempts = 3
        item = repo._to_item_low_level(user)

        assert item["failed_login_attempts"] == {"N": "3"}

    def test_require_password_change_is_attribute_value_bool(self) -> None:

        repo = make_repo()
        user = make_user()
        user.require_password_change = False
        item = repo._to_item_low_level(user)

        assert item["require_password_change"] == {"BOOL": False}

    def test_is_admin_is_attribute_value_bool(self) -> None:

        repo = make_repo()
        user = make_user()
        user.is_admin = False
        item = repo._to_item_low_level(user)

        assert item["is_admin"] == {"BOOL": False}

    def test_created_at_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user()
        item = repo._to_item_low_level(user)

        assert item["created_at"] == {"S": user.created_at.isoformat()}

    def test_updated_at_is_attribute_value_string(self) -> None:

        repo = make_repo()
        user = make_user()
        item = repo._to_item_low_level(user)

        assert item["updated_at"] == {"S": user.updated_at.isoformat()}

    def test_optional_none_fields_are_omitted(self) -> None:
        """None optional fields must not appear in the item — never store NULL."""

        repo = make_repo()
        user = make_user()
        # Ensure all optional fields are None
        assert user.account_locked_until is None
        assert user.last_login_at is None
        assert user.last_password_change is None
        assert user.email_verification_token is None
        assert user.email_verified_at is None

        item = repo._to_item_low_level(user)

        assert "account_locked_until" not in item
        assert "last_login_at" not in item
        assert "last_password_change" not in item
        assert "email_verification_token" not in item
        assert "email_verified_at" not in item

    def test_optional_datetime_fields_included_when_set(self) -> None:

        repo = make_repo()
        user = make_user()
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        user.last_login_at = ts
        item = repo._to_item_low_level(user)

        assert item["last_login_at"] == {"S": ts.isoformat()}

    def test_email_verification_token_included_when_set(self) -> None:

        repo = make_repo()
        user = make_user()
        user.email_verification_token = "tok-abc-123"
        item = repo._to_item_low_level(user)

        assert item["email_verification_token"] == {"S": "tok-abc-123"}


# ── save_operation() ──────────────────────────────────────────────────────────


class TestSaveOperation:
    """save_operation() must return a TransactionalOperation without calling put_item."""

    def test_returns_transactional_operation(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.save_operation(user)

        assert isinstance(result, TransactionalOperation)

    def test_operation_type_is_put(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.save_operation(user)

        assert result.operation_type == "Put"

    def test_includes_table_name(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.save_operation(user)

        assert result.params["TableName"] == "ugsys-users-test"

    def test_condition_expression_is_attribute_not_exists(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.save_operation(user)

        assert result.params["ConditionExpression"] == "attribute_not_exists(pk)"

    def test_item_uses_low_level_attribute_value_format(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.save_operation(user)

        item = result.params["Item"]
        # pk must be {"S": "..."} not a plain string
        assert isinstance(item["pk"], dict)
        assert "S" in item["pk"]

    def test_does_not_call_put_item(self) -> None:
        """save_operation is synchronous — must NOT perform any I/O."""

        repo = make_repo()
        user = make_user()
        # session must not be touched
        repo._session.resource.assert_not_called = MagicMock()

        repo.save_operation(user)

        repo._session.resource.assert_not_called()

    def test_is_synchronous(self) -> None:
        import inspect

        from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

        assert not inspect.iscoroutinefunction(DynamoDBUserRepository.save_operation)


# ── update_operation() ────────────────────────────────────────────────────────


class TestUpdateOperation:
    """update_operation() must return a TransactionalOperation without calling put_item."""

    def test_returns_transactional_operation(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.update_operation(user)

        assert isinstance(result, TransactionalOperation)

    def test_operation_type_is_put(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.update_operation(user)

        assert result.operation_type == "Put"

    def test_includes_table_name(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.update_operation(user)

        assert result.params["TableName"] == "ugsys-users-test"

    def test_condition_expression_is_attribute_exists(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.update_operation(user)

        assert result.params["ConditionExpression"] == "attribute_exists(pk)"

    def test_item_uses_low_level_attribute_value_format(self) -> None:

        repo = make_repo()
        user = make_user()

        result = repo.update_operation(user)

        item = result.params["Item"]
        assert isinstance(item["pk"], dict)
        assert "S" in item["pk"]

    def test_does_not_call_put_item(self) -> None:

        repo = make_repo()
        user = make_user()

        repo.update_operation(user)

        repo._session.resource.assert_not_called()

    def test_is_synchronous(self) -> None:
        import inspect

        from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

        assert not inspect.iscoroutinefunction(DynamoDBUserRepository.update_operation)

    def test_differs_from_save_operation_in_condition(self) -> None:
        """save_operation and update_operation must have different ConditionExpressions."""

        repo = make_repo()
        user = make_user()

        save_op = repo.save_operation(user)
        update_op = repo.update_operation(user)

        assert save_op.params["ConditionExpression"] != update_op.params["ConditionExpression"]


# ── Existing methods unchanged ────────────────────────────────────────────────


class TestExistingMethodsUnchanged:
    """Adding new methods must not break existing save() and update() signatures."""

    def test_save_method_still_exists(self) -> None:
        import inspect

        from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

        assert inspect.iscoroutinefunction(DynamoDBUserRepository.save)

    def test_update_method_still_exists(self) -> None:
        import inspect

        from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

        assert inspect.iscoroutinefunction(DynamoDBUserRepository.update)
