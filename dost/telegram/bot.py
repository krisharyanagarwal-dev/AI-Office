"""Telegram bot for dost - commands and proactive notifications.

Uses aiogram 3.x for async bot handling.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from aiogram import Bot, Dispatcher, Router, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message, BotCommand
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties
    AIOMGRAM_AVAILABLE = True
except ImportError:
    AIOMGRAM_AVAILABLE = False
    Bot = Dispatcher = Router = F = Command = CommandStart = Message = BotCommand = ParseMode = DefaultBotProperties = None


def _require_aiogram():
    """Check aiogram availability, raise if not available."""
    if not AIOMGRAM_AVAILABLE:
        raise RuntimeError("aiogram not installed. Run: pip install aiogram")


class DostTelegramBot:
    """Telegram bot for dost with fleet integration."""

    def __init__(self, token: str | None = None, chat_id: int | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or (int(os.environ["TELEGRAM_CHAT_ID"]) if os.environ.get("TELEGRAM_CHAT_ID") else None)
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self._running = False

        _require_aiogram()

        # Validate required config
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID not set")

    def _get_dispatcher(self) -> Dispatcher:
        """Create and configure dispatcher with routes."""
        if self.dp is not None:
            return self.dp

        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self.dp = Dispatcher()
        router = Router()

        # Commands
        router.message(CommandStart())(self._cmd_start)
        router.message(Command("briefing"))(self._cmd_briefing)
        router.message(Command("status"))(self._cmd_status)
        router.message(Command("dispatch"))(self._cmd_dispatch)
        router.message(Command("memory"))(self._cmd_memory)
        router.message(Command("help"))(self._cmd_help)

        # Text messages (dispatch to fleet)
        router.message(F.text & ~F.text.startswith("/"))(self._on_text)

        self.dp.include_router(router)
        return self.dp

    async def _cmd_start(self, message: Message):
        """Handle /start command."""
        await message.answer(
            "🤖 *Dost Telegram Bot*\n\n"
            "Commands:\n"
            "• `/briefing` - Get morning market briefing\n"
            "• `/status` - Fleet & system status\n"
            "• `/dispatch <prompt>` - Send task to fleet\n"
            "• `/memory` - Show conversation memory\n"
            "• `/help` - Show this help\n\n"
            "Or just type a message to dispatch to the fleet.",
        )

    async def _cmd_help(self, message: Message):
        """Handle /help command."""
        await self._cmd_start(message)

    async def _cmd_briefing(self, message: Message):
        """Handle /briefing command - generate and send morning briefing."""
        await message.answer("📊 Generating briefing...")

        # Run dost briefing via CLI
        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--briefing"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                # Truncate if too long for Telegram
                text = result.stdout[:3500]
                await message.answer(f"📈 *Morning Briefing*\n\n{text}")
            else:
                await message.answer(f"❌ Briefing failed: {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            await message.answer("⏱️ Briefing timed out")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_status(self, message: Message):
        """Handle /status command - show fleet status."""
        await message.answer("🔍 Checking fleet status...")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--status"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                text = result.stdout[:3500]
                await message.answer(f"📊 *Fleet Status*\n\n{text}")
            else:
                await message.answer(f"❌ Status failed: {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            await message.answer("⏱️ Status timed out")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_dispatch(self, message: Message):
        """Handle /dispatch command - send prompt to fleet."""
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: `/dispatch <your prompt>`")
            return

        prompt = args[1]
        await message.answer(f"📤 Dispatching: *{prompt[:100]}...*")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--dispatch", prompt],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    task_id = data.get("task_id", "unknown")
                    agent_id = data.get("agent_id", "unknown")
                    await message.answer(
                        f"✅ *Dispatched*\n"
                        f"Task: `{task_id}`\n"
                        f"Agent: `{agent_id}`\n"
                        f"Prompt: {prompt[:200]}"
                    )
                else:
                    await message.answer(f"❌ Dispatch failed: {data.get('error', 'unknown')}")
            else:
                await message.answer(f"❌ Dispatch failed: {result.stderr[:500]}")
        except json.JSONDecodeError:
            await message.answer(f"❌ Invalid response: {result.stdout[:500]}")
        except subprocess.TimeoutExpired:
            await message.answer("⏱️ Dispatch timed out")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_memory(self, message: Message):
        """Handle /memory command - show conversation memory."""
        try:
            memory_path = Path(__file__).resolve().parents[1] / "jarvis_memory" / "conversations.jsonl"
            if memory_path.exists():
                lines = memory_path.read_text().strip().split("\n")
                recent = lines[-5:] if lines else []
                text = "\n".join(recent) if recent else "No memory yet"
                await message.answer(f"🧠 *Recent Memory*\n\n{text[:3500]}")
            else:
                await message.answer("🧠 No memory file found")
        except Exception as e:
            await message.answer(f"❌ Error reading memory: {e}")

    async def _on_text(self, message: Message):
        """Handle plain text messages - dispatch to fleet."""
        prompt = message.text.strip()
        if not prompt:
            return

        await message.answer(f"📤 Dispatching: *{prompt[:100]}...*")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--dispatch", prompt],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    task_id = data.get("task_id", "unknown")
                    agent_id = data.get("agent_id", "unknown")
                    await message.answer(
                        f"✅ *Dispatched*\n"
                        f"Task: `{task_id}`\n"
                        f"Agent: `{agent_id}`"
                    )
                else:
                    await message.answer(f"❌ Dispatch failed: {data.get('error', 'unknown')}")
            else:
                await message.answer(f"❌ Dispatch failed: {result.stderr[:500]}")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def start_polling(self):
        """Start bot polling."""
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID not set")

        dp = self._get_dispatcher()

        # Set bot commands
        await self.bot.set_my_commands([
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="briefing", description="Get morning briefing"),
            BotCommand(command="status", description="Fleet status"),
            BotCommand(command="dispatch", description="Send task to fleet"),
            BotCommand(command="memory", description="Show memory"),
            BotCommand(command="help", description="Show help"),
        ])

        self._running = True
        print(f"[telegram] Bot started, listening for commands...")
        await dp.start_polling(self.bot)

    async def send_message(self, text: str, parse_mode: str = "Markdown"):
        """Send a message to the configured chat."""
        if not self.bot:
            self.bot = Bot(token=self.token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        try:
            await self.bot.send_message(self.chat_id, text, parse_mode=parse_mode)
        except Exception as e:
            print(f"[telegram] Failed to send message: {e}")

    async def send_proactive_briefing(self):
        """Send proactive morning briefing."""
        await self.send_message("🌅 *Good morning! Generating your daily briefing...*")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--briefing"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                text = result.stdout[:3500]
                await self.send_message(f"📈 *Daily Briefing*\n\n{text}")
            else:
                await self.send_message(f"❌ Briefing failed: {result.stderr[:500]}")
        except Exception as e:
            await self.send_message(f"❌ Briefing error: {e}")

    async def send_anomaly_alert(self, alert_type: str, details: str):
        """Send anomaly alert."""
        await self.send_message(f"⚠️ *Anomaly Alert: {alert_type}*\n\n{details[:3500]}")

    async def stop(self):
        """Stop the bot."""
        self._running = False
        if self.bot:
            await self.bot.session.close()


async def main():
    """Entry point for running the bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)

    bot = DostTelegramBot(token, int(chat_id))
    try:
        await bot.start_polling()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())