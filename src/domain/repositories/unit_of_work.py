"""Unit of Work domain port.

Defines the UnitOfWork ABC and TransactionalOperation dataclass.
Zero imports from infrastructure, application, or presentation layers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TransactionalOperation:
    """Represents a single write operation within a DynamoDB transaction."""

    operation_type: str  # "Put", "Update", or "Delete"
    params: dict[str, Any]


class UnitOfWork(ABC):
    """Abstract port for executing multiple repository operations atomically."""

    @abstractmethod
    async def execute(self, operations: list[TransactionalOperation]) -> None:
        """Execute all operations atomically. All succeed or all fail."""
        ...
