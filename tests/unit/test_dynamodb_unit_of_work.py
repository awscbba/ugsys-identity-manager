"""Unit tests for DynamoDBUnitOfWork.

TDD: RED phase — tests written before implementation.
All tests mock the aioboto3 DynamoDB client at the port boundary.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError

from src.domain.exceptions import RepositoryError
from src.domain.repositories.unit_of_work import TransactionalOperation

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_op(
    operation_type: str = "Put",
    table: str = "test-table",
    pk: str = "USER#123",
) -> TransactionalOperation:
    return TransactionalOperation(
        operation_type=operation_type,
        params={
            "TableName": table,
            "Item": {"PK": {"S": pk}, "SK": {"S": "PROFILE"}},
        },
    )


def make_client_error(code: str = "InternalServerError") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "test error"}},
        operation_name="TransactWriteItems",
    )


def make_cancellation_error() -> ClientError:
    err = ClientError(
        error_response={
            "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
            "CancellationReasons": [
                {"Code": "ConditionalCheckFailed", "Message": "condition failed"},
                {"Code": "None", "Message": ""},
            ],
        },
        operation_name="TransactWriteItems",
    )
    return err


def make_uow(mock_client: Any) -> Any:
    """Create a DynamoDBUnitOfWork with a pre-wired mock client."""
    from src.infrastructure.persistence.dynamodb_unit_of_work import DynamoDBUnitOfWork

    uow = DynamoDBUnitOfWork.__new__(DynamoDBUnitOfWork)
    uow._client = mock_client
    return uow


# ── Empty list guard ──────────────────────────────────────────────────────────


class TestEmptyList:
    """execute() with an empty list must return immediately without any DynamoDB call."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_none(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)

        result = await uow.execute([])

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_list_does_not_call_transact_write_items(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)

        await uow.execute([])

        mock_client.transact_write_items.assert_not_called()


# ── Oversized batch guard ─────────────────────────────────────────────────────


class TestOversizedBatch:
    """execute() with > 100 operations must raise RepositoryError without calling DynamoDB."""

    @pytest.mark.asyncio
    async def test_101_operations_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)
        ops = [make_op() for _ in range(101)]

        with pytest.raises(RepositoryError):
            await uow.execute(ops)

    @pytest.mark.asyncio
    async def test_200_operations_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)
        ops = [make_op() for _ in range(200)]

        with pytest.raises(RepositoryError):
            await uow.execute(ops)

    @pytest.mark.asyncio
    async def test_oversized_batch_does_not_call_transact_write_items(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)
        ops = [make_op() for _ in range(101)]

        with pytest.raises(RepositoryError):
            await uow.execute(ops)

        mock_client.transact_write_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_oversized_error_has_safe_user_message(self) -> None:
        mock_client = AsyncMock()
        uow = make_uow(mock_client)
        ops = [make_op() for _ in range(101)]

        with pytest.raises(RepositoryError) as exc_info:
            await uow.execute(ops)

        assert exc_info.value.user_message == "An unexpected error occurred"

    @pytest.mark.asyncio
    async def test_100_operations_does_not_raise(self) -> None:
        """Exactly 100 operations is the boundary — must NOT raise."""
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)
        ops = [make_op() for _ in range(100)]

        # Should not raise
        await uow.execute(ops)

        mock_client.transact_write_items.assert_called_once()


# ── Valid batch execution ─────────────────────────────────────────────────────


class TestValidBatch:
    """execute() with 1-100 operations must call transact_write_items exactly once."""

    @pytest.mark.asyncio
    async def test_single_operation_calls_transact_write_items(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)

        await uow.execute([make_op()])

        mock_client.transact_write_items.assert_called_once()

    @pytest.mark.asyncio
    async def test_two_operations_calls_transact_write_items_once(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)

        await uow.execute([make_op(), make_op(pk="OUTBOX#456")])

        mock_client.transact_write_items.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_operations_forwarded_to_transact_write_items(self) -> None:
        """Every operation must appear in the TransactItems list."""
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)
        ops = [make_op(pk=f"USER#{i}") for i in range(5)]

        await uow.execute(ops)

        call_kwargs = mock_client.transact_write_items.call_args[1]
        transact_items = call_kwargs["TransactItems"]
        assert len(transact_items) == 5

    @pytest.mark.asyncio
    async def test_operations_wrapped_in_correct_operation_type_key(self) -> None:
        """Each TransactItem must be {operation_type: params}."""
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)
        put_op = make_op(operation_type="Put")
        delete_op = TransactionalOperation(
            operation_type="Delete",
            params={"TableName": "t", "Key": {"PK": {"S": "X"}}},
        )

        await uow.execute([put_op, delete_op])

        call_kwargs = mock_client.transact_write_items.call_args[1]
        transact_items = call_kwargs["TransactItems"]
        assert "Put" in transact_items[0]
        assert "Delete" in transact_items[1]

    @pytest.mark.asyncio
    async def test_execute_returns_none_on_success(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        uow = make_uow(mock_client)

        result = await uow.execute([make_op()])

        assert result is None


# ── TransactionCanceledException handling ─────────────────────────────────────


class TestTransactionCanceledException:
    """TransactionCanceledException must log cancellation reasons and raise RepositoryError."""

    @pytest.mark.asyncio
    async def test_transaction_cancelled_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(side_effect=make_cancellation_error())
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError):
            await uow.execute([make_op()])

    @pytest.mark.asyncio
    async def test_transaction_cancelled_error_has_safe_user_message(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(side_effect=make_cancellation_error())
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError) as exc_info:
            await uow.execute([make_op()])

        assert exc_info.value.user_message == "An unexpected error occurred"

    @pytest.mark.asyncio
    async def test_transaction_cancelled_does_not_propagate_raw_client_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(side_effect=make_cancellation_error())
        uow = make_uow(mock_client)

        try:
            await uow.execute([make_op()])
        except RepositoryError:
            pass
        except ClientError:
            pytest.fail("Raw ClientError must not propagate — must be wrapped in RepositoryError")


# ── Other ClientError handling ────────────────────────────────────────────────


class TestOtherClientErrors:
    """Any non-cancellation ClientError must be wrapped in RepositoryError."""

    @pytest.mark.asyncio
    async def test_internal_server_error_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(
            side_effect=make_client_error("InternalServerError")
        )
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError):
            await uow.execute([make_op()])

    @pytest.mark.asyncio
    async def test_provisioned_throughput_exceeded_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(
            side_effect=make_client_error("ProvisionedThroughputExceededException")
        )
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError):
            await uow.execute([make_op()])

    @pytest.mark.asyncio
    async def test_throttling_raises_repository_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(
            side_effect=make_client_error("ThrottlingException")
        )
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError):
            await uow.execute([make_op()])

    @pytest.mark.asyncio
    async def test_client_error_has_safe_user_message(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(
            side_effect=make_client_error("InternalServerError")
        )
        uow = make_uow(mock_client)

        with pytest.raises(RepositoryError) as exc_info:
            await uow.execute([make_op()])

        assert exc_info.value.user_message == "An unexpected error occurred"
        # Internal message must differ from user_message
        assert exc_info.value.message != exc_info.value.user_message

    @pytest.mark.asyncio
    async def test_client_error_does_not_propagate_raw(self) -> None:
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(
            side_effect=make_client_error("ServiceUnavailable")
        )
        uow = make_uow(mock_client)

        try:
            await uow.execute([make_op()])
        except RepositoryError:
            pass
        except ClientError:
            pytest.fail("Raw ClientError must not propagate — must be wrapped in RepositoryError")


# ── Implements UnitOfWork ABC ─────────────────────────────────────────────────


class TestImplementsUnitOfWork:
    """DynamoDBUnitOfWork must be a concrete implementation of UnitOfWork."""

    def test_is_subclass_of_unit_of_work(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork
        from src.infrastructure.persistence.dynamodb_unit_of_work import DynamoDBUnitOfWork

        assert issubclass(DynamoDBUnitOfWork, UnitOfWork)

    def test_can_be_instantiated_with_client(self) -> None:
        from src.infrastructure.persistence.dynamodb_unit_of_work import DynamoDBUnitOfWork

        mock_client = AsyncMock()
        uow = DynamoDBUnitOfWork(client=mock_client)
        assert uow is not None
