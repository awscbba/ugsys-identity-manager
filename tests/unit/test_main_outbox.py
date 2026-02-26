"""Smoke tests for main_outbox.py Lambda handler wiring.

TDD: RED → GREEN phase.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_processor(published: int = 3) -> AsyncMock:
    mock = AsyncMock()
    mock.process_pending.return_value = published
    return mock


class TestHandlerWiring:
    @pytest.mark.asyncio
    async def test_handler_calls_process_pending(self) -> None:
        """handler() must invoke OutboxProcessor.process_pending() and return without error."""
        mock_processor = _make_mock_processor(published=3)

        with patch("src.main_outbox._build_processor", new=AsyncMock(return_value=mock_processor)):
            from src.main_outbox import handler

            result = await handler({}, MagicMock())

        mock_processor.process_pending.assert_awaited_once()
        assert result["published"] == 3

    @pytest.mark.asyncio
    async def test_handler_returns_published_count(self) -> None:
        """handler() return dict must include 'published' key with the count."""
        mock_processor = _make_mock_processor(published=7)

        with patch("src.main_outbox._build_processor", new=AsyncMock(return_value=mock_processor)):
            from src.main_outbox import handler

            result = await handler({}, MagicMock())

        assert result["published"] == 7

    @pytest.mark.asyncio
    async def test_handler_returns_status_ok(self) -> None:
        """handler() return dict must include 'status': 'ok'."""
        mock_processor = _make_mock_processor(published=0)

        with patch("src.main_outbox._build_processor", new=AsyncMock(return_value=mock_processor)):
            from src.main_outbox import handler

            result = await handler({}, MagicMock())

        assert result["status"] == "ok"

    def test_sync_handler_exists(self) -> None:
        """A synchronous sync_handler must exist for Lambda runtime compatibility."""
        import src.main_outbox as mod

        assert callable(mod.sync_handler)
