"""Unit tests for UnitOfWork ABC and TransactionalOperation dataclass.

TDD: RED phase — these tests will fail until the implementation exists.
"""

import inspect
from dataclasses import fields
from typing import Any

import pytest


class TestTransactionalOperation:
    """Tests for the TransactionalOperation dataclass."""

    def test_transactional_operation_has_operation_type_field(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        field_names = {f.name for f in fields(TransactionalOperation)}
        assert "operation_type" in field_names

    def test_transactional_operation_has_params_field(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        field_names = {f.name for f in fields(TransactionalOperation)}
        assert "params" in field_names

    def test_transactional_operation_can_be_instantiated(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        op = TransactionalOperation(operation_type="Put", params={"TableName": "test"})
        assert op.operation_type == "Put"
        assert op.params == {"TableName": "test"}

    def test_transactional_operation_is_dataclass(self) -> None:
        import dataclasses

        from src.domain.repositories.unit_of_work import TransactionalOperation

        assert dataclasses.is_dataclass(TransactionalOperation)

    def test_transactional_operation_operation_type_is_str(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        type_hints = TransactionalOperation.__dataclass_fields__
        assert type_hints["operation_type"].type in (str, "str")

    def test_transactional_operation_params_is_dict(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        op = TransactionalOperation(operation_type="Delete", params={"key": "value"})
        assert isinstance(op.params, dict)

    def test_transactional_operation_accepts_any_dict_params(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation

        params: dict[str, Any] = {
            "TableName": "my-table",
            "Item": {"PK": {"S": "USER#123"}, "SK": {"S": "USER"}},
            "ConditionExpression": "attribute_not_exists(PK)",
        }
        op = TransactionalOperation(operation_type="Put", params=params)
        assert op.params["TableName"] == "my-table"


class TestUnitOfWork:
    """Tests for the UnitOfWork ABC."""

    def test_unit_of_work_is_abstract(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork

        assert inspect.isabstract(UnitOfWork)

    def test_unit_of_work_cannot_be_instantiated_directly(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork

        with pytest.raises(TypeError):
            UnitOfWork()  # type: ignore[abstract]

    def test_unit_of_work_declares_execute_abstract_method(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork

        assert "execute" in UnitOfWork.__abstractmethods__

    def test_unit_of_work_execute_is_coroutine_function(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork

        # The abstract method should be declared as async
        execute_method = UnitOfWork.execute
        assert inspect.iscoroutinefunction(execute_method)

    def test_unit_of_work_concrete_subclass_must_implement_execute(self) -> None:
        from src.domain.repositories.unit_of_work import TransactionalOperation, UnitOfWork

        class ConcreteUoW(UnitOfWork):
            async def execute(self, operations: list[TransactionalOperation]) -> None:
                pass

        # Should not raise
        uow = ConcreteUoW()
        assert uow is not None

    def test_unit_of_work_subclass_missing_execute_raises_type_error(self) -> None:
        from src.domain.repositories.unit_of_work import UnitOfWork

        class IncompleteUoW(UnitOfWork):
            pass

        with pytest.raises(TypeError):
            IncompleteUoW()  # type: ignore[abstract]

    def test_unit_of_work_has_no_infra_imports(self) -> None:
        """Domain layer must have zero imports from infra/application/presentation."""
        import ast
        import pathlib

        source_path = pathlib.Path("src/domain/repositories/unit_of_work.py")
        if not source_path.exists():
            pytest.skip("Implementation not yet created")

        source = source_path.read_text()
        tree = ast.parse(source)

        forbidden_prefixes = (
            "src.infrastructure",
            "src.application",
            "src.presentation",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    assert not node.module.startswith(prefix), (
                        f"Domain layer must not import from {prefix}, found: from {node.module}"
                    )
