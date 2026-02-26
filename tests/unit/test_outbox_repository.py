"""Unit tests for OutboxRepository ABC.

TDD: RED phase — these tests will fail until the implementation exists.
"""

import inspect

import pytest


class TestOutboxRepositoryAbstractMethods:
    """Tests that OutboxRepository declares all required abstract methods."""

    def test_outbox_repository_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.isabstract(OutboxRepository)

    def test_outbox_repository_cannot_be_instantiated_directly(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        with pytest.raises(TypeError):
            OutboxRepository()  # type: ignore[abstract]

    def test_save_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "save" in OutboxRepository.__abstractmethods__

    def test_find_pending_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "find_pending" in OutboxRepository.__abstractmethods__

    def test_mark_published_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "mark_published" in OutboxRepository.__abstractmethods__

    def test_increment_retry_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "increment_retry" in OutboxRepository.__abstractmethods__

    def test_mark_failed_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "mark_failed" in OutboxRepository.__abstractmethods__

    def test_save_operation_is_abstract(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert "save_operation" in OutboxRepository.__abstractmethods__

    def test_all_six_abstract_methods_declared(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        expected = {
            "save",
            "find_pending",
            "mark_published",
            "increment_retry",
            "mark_failed",
            "save_operation",
        }
        assert expected.issubset(OutboxRepository.__abstractmethods__)


class TestOutboxRepositoryAsyncMethods:
    """Tests that async methods are declared as coroutine functions."""

    def test_save_is_coroutine_function(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.iscoroutinefunction(OutboxRepository.save)

    def test_find_pending_is_coroutine_function(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.iscoroutinefunction(OutboxRepository.find_pending)

    def test_mark_published_is_coroutine_function(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.iscoroutinefunction(OutboxRepository.mark_published)

    def test_increment_retry_is_coroutine_function(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.iscoroutinefunction(OutboxRepository.increment_retry)

    def test_mark_failed_is_coroutine_function(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert inspect.iscoroutinefunction(OutboxRepository.mark_failed)

    def test_save_operation_is_not_coroutine_function(self) -> None:
        """save_operation is synchronous — it builds a TransactionalOperation without I/O."""
        from src.domain.repositories.outbox_repository import OutboxRepository

        assert not inspect.iscoroutinefunction(OutboxRepository.save_operation)


class TestOutboxRepositoryConcreteSubclass:
    """Tests that a concrete subclass implementing all methods can be instantiated."""

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        from src.domain.entities.outbox_event import OutboxEvent
        from src.domain.repositories.outbox_repository import OutboxRepository
        from src.domain.repositories.unit_of_work import TransactionalOperation

        class ConcreteRepo(OutboxRepository):
            async def save(self, event: OutboxEvent) -> OutboxEvent:
                return event

            async def find_pending(self, limit: int) -> list[OutboxEvent]:
                return []

            async def mark_published(self, event_id: str) -> None:
                pass

            async def increment_retry(self, event_id: str) -> None:
                pass

            async def mark_failed(self, event_id: str) -> None:
                pass

            def save_operation(self, event: OutboxEvent) -> TransactionalOperation:
                return TransactionalOperation(operation_type="Put", params={})

        repo = ConcreteRepo()
        assert repo is not None

    def test_incomplete_subclass_raises_type_error(self) -> None:
        from src.domain.repositories.outbox_repository import OutboxRepository

        class IncompleteRepo(OutboxRepository):
            pass

        with pytest.raises(TypeError):
            IncompleteRepo()  # type: ignore[abstract]


class TestOutboxRepositoryPurity:
    """Tests that OutboxRepository has zero external layer imports."""

    def test_outbox_repository_has_no_infra_imports(self) -> None:
        import ast
        import pathlib

        source_path = pathlib.Path("src/domain/repositories/outbox_repository.py")
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
