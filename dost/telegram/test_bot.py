"""Tests for Telegram bot module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram import DostTelegramBot
from telegram.bot import _require_aiogram


@pytest.fixture(autouse=True)
def mock_aiogram(monkeypatch):
    """Mock aiogram availability for all tests."""
    monkeypatch.setattr("telegram.bot.AIOMGRAM_AVAILABLE", True)
    # Mock the imports
    import types
    mock_aiogram = types.ModuleType("aiogram")
    mock_aiogram.Bot = MagicMock
    mock_aiogram.Dispatcher = MagicMock
    mock_aiogram.Router = MagicMock
    mock_aiogram.F = MagicMock()
    mock_aiogram.enums = types.ModuleType("enums")
    mock_aiogram.enums.ParseMode = "MARKDOWN"
    mock_aiogram.client = types.ModuleType("client")
    mock_aiogram.client.default = types.ModuleType("default")
    mock_aiogram.client.default.DefaultBotProperties = MagicMock
    mock_aiogram.filters = types.ModuleType("filters")
    mock_aiogram.filters.Command = MagicMock
    mock_aiogram.filters.CommandStart = MagicMock
    mock_aiogram.types = types.ModuleType("types")
    mock_aiogram.types.Message = MagicMock
    mock_aiogram.types.BotCommand = MagicMock

    monkeypatch.setitem(sys.modules, "aiogram", mock_aiogram)
    monkeypatch.setitem(sys.modules, "aiogram.enums", mock_aiogram.enums)
    monkeypatch.setitem(sys.modules, "aiogram.client", mock_aiogram.client)
    monkeypatch.setitem(sys.modules, "aiogram.client.default", mock_aiogram.client.default)
    monkeypatch.setitem(sys.modules, "aiogram.filters", mock_aiogram.filters)
    monkeypatch.setitem(sys.modules, "aiogram.types", mock_aiogram.types)

    yield

    # Clean up
    for mod in ["aiogram", "aiogram.enums", "aiogram.client", "aiogram.client.default", "aiogram.filters", "aiogram.types"]:
        if mod in sys.modules:
            del sys.modules[mod]


class TestDostTelegramBot:
    """Tests for DostTelegramBot."""

    def test_bot_requires_token(self, monkeypatch):
        """Bot raises error without token."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN not set"):
            DostTelegramBot(token=None, chat_id=12345)

    def test_bot_requires_chat_id(self, monkeypatch):
        """Bot raises error without chat_id."""
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID not set"):
            DostTelegramBot(token="test_token", chat_id=None)

    @pytest.mark.skipif(
        "aiogram" not in sys.modules,
        reason="aiogram not installed",
    )
    def test_dispatcher_creation(self):
        """Dispatcher is created with routes."""
        bot = DostTelegramBot(token="test_token", chat_id=12345)
        dp = bot._get_dispatcher()
        assert dp is not None
        # Check that routes are registered
        assert len(dp.resolve_used_update_types()) > 0

    @pytest.mark.asyncio
    async def test_send_message_mock(self):
        """Test send_message with mocked bot."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            bot = DostTelegramBot(token="test_token", chat_id=12345)
            bot.bot = mock_bot

            await bot.send_message("Test message")

            mock_bot.send_message.assert_called_once_with(12345, "Test message", parse_mode="Markdown")

    @pytest.mark.asyncio
    async def test_send_proactive_briefing_mock(self):
        """Test proactive briefing with mocked subprocess."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            with patch("telegram.bot.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="Briefing content here",
                    stderr="",
                )

                bot = DostTelegramBot(token="test_token", chat_id=12345)
                bot.bot = mock_bot

                await bot.send_proactive_briefing()

                mock_bot.send_message.assert_called()
                # Check that briefing was sent
                call_args = mock_bot.send_message.call_args[0]
                assert "Daily Briefing" in call_args[1]

    @pytest.mark.asyncio
    async def test_send_anomaly_alert_mock(self):
        """Test anomaly alert."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            bot = DostTelegramBot(token="test_token", chat_id=12345)
            bot.bot = mock_bot

            await bot.send_anomaly_alert("Cost Spike", "Daily cost exceeded threshold")

            mock_bot.send_message.assert_called_once()
            call_args = mock_bot.send_message.call_args[0]
            assert "Anomaly Alert: Cost Spike" in call_args[1]
            assert "Daily cost exceeded threshold" in call_args[1]


class TestBotCommands:
    """Test bot command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_start(self):
        """Test /start command handler."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            bot = DostTelegramBot(token="test_token", chat_id=12345)
            bot.bot = mock_bot

            # Mock message
            mock_message = AsyncMock()
            mock_message.answer = AsyncMock()

            await bot._cmd_start(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "Dost Telegram Bot" in call_args
            assert "/briefing" in call_args
            assert "/status" in call_args

    @pytest.mark.asyncio
    async def test_cmd_dispatch_no_args(self):
        """Test /dispatch without arguments."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            bot = DostTelegramBot(token="test_token", chat_id=12345)
            bot.bot = mock_bot

            mock_message = AsyncMock()
            mock_message.text = "/dispatch"
            mock_message.answer = AsyncMock()

            await bot._cmd_dispatch(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "Usage:" in call_args

    @pytest.mark.asyncio
    async def test_cmd_dispatch_with_args(self):
        """Test /dispatch with arguments."""
        with patch("telegram.bot.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value = mock_bot

            with patch("telegram.bot.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='{"ok": true, "task_id": "jev-abc123", "agent_id": "research-analyst"}',
                    stderr="",
                )

                bot = DostTelegramBot(token="test_token", chat_id=12345)
                bot.bot = mock_bot

                mock_message = AsyncMock()
                mock_message.text = "/dispatch research AAPL"
                mock_message.answer = AsyncMock()

                await bot._cmd_dispatch(mock_message)

                mock_message.answer.assert_called()
                # First call: "Dispatching..."
                # Second call: result
                assert mock_message.answer.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])