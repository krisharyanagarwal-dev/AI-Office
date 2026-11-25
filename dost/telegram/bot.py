"""Telegram bot for dost - commands and proactive notifications.

Uses aiogram 3.x for async bot handling.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dost.dost_main import (
    dispatch_prompt_to_fleet,
    generate_daily_briefing,
    _fetch_dispatcher_status,
    run_web_search,
)

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
        router.message(Command("search"))(self._cmd_search)
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
            "• `/briefing --dry-run` - Preview briefing without sending\n"
            "• `/status` - Fleet & system status\n"
            "• `/dispatch <prompt>` - Send task to fleet\n"
            "• `/dispatch --dry-run <prompt>` - Preview without submitting\n"
            "• `/search <query>` - Search the web\n"
            "• `/memory` - Show conversation memory\n"
            "• `/help` - Show this help\n\n"
            "Or just type a message to dispatch to the fleet.",
        )

    async def _cmd_help(self, message: Message):
        """Handle /help command."""
        await self._cmd_start(message)

    async def _cmd_briefing(self, message: Message):
        """Handle /briefing command - generate and send morning briefing.

        Optional leading `--dry-run` generates the briefing and presents it as a
        preview without the normal send framing.
        """
        args = message.text.split(maxsplit=1)
        dry_run = False
        if len(args) == 2 and args[1] == "--dry-run":
            dry_run = True

        await message.answer("📊 Generating briefing...")

        # Generate briefing in-process (dost.dost module was removed; shell-outs are broken)
        try:
            text = generate_daily_briefing()
            if dry_run:
                await message.answer(
                    f"🧪 *Dry run — briefing preview (not sent)*\n\n{text[:3500]}"
                )
            else:
                await message.answer(f"📈 *Morning Briefing*\n\n{text[:3500]}")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_status(self, message: Message):
        """Handle /status command - show fleet status."""
        await message.answer("🔍 Checking fleet status...")

        # Read fleet status in-process (dost.dost module was removed; shell-outs are broken)
        try:
            st = _fetch_dispatcher_status()
            if st:
                text = json.dumps(st, indent=2)[:3500]
            else:
                text = "Fleet status: unreachable (dispatcher may be down)."
            await message.answer(f"📊 *Fleet Status*\n\n{text}")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_dispatch(self, message: Message):
        """Handle /dispatch command - send prompt to fleet.

        Optional leading `--dry-run` previews the task without submitting it.
        """
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "Usage: `/dispatch <your prompt>`\n"
                "Try: `/dispatch --dry-run research AAPL` to preview without submitting."
            )
            return

        rest = args[1]
        dry_run = False
        if rest.startswith("--dry-run"):
            dry_run = True
            rest = rest[len("--dry-run"):].strip()
            if not rest:
                await message.answer("Usage: `/dispatch --dry-run <your prompt>`")
                return

        prompt = rest
        await message.answer(f"📤 Dispatching: *{prompt[:100]}...*")

        # Dispatch in-process (dost.dost module was removed; shell-outs are broken)
        try:
            result = dispatch_prompt_to_fleet(prompt, dry_run=dry_run)
            if result.get("ok"):
                task_id = result.get("task_id", "unknown")
                agent_id = result.get("agent_id", "unknown")
                if dry_run:
                    await message.answer(
                        f"🧪 *Dry run — nothing submitted*\n"
                        f"Task: `{task_id}`\n"
                        f"Agent: `{agent_id}`\n"
                        f"Priority: {result.get('priority', 'normal')}\n"
                        f"{result.get('message', '')}"
                    )
                else:
                    await message.answer(
                        f"✅ *Dispatched*\n"
                        f"Task: `{task_id}`\n"
                        f"Agent: `{agent_id}`\n"
                        f"Prompt: {prompt[:200]}"
                    )
            else:
                await message.answer(f"❌ Dispatch failed: {result.get('error', 'unknown')}")
        except Exception as e:
            await message.answer(f"❌ Error: {e}")

    async def _cmd_search(self, message: Message):
        """Handle /search command - run a keyless web search."""
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: `/search <your query>`")
            return

        query = args[1]
        await message.answer(f"🔍 Searching: *{query[:100]}...*")

        try:
            results = run_web_search(query)
            await message.answer(f"🔎 *Web search results*\n\n{results[:3500]}")
        except Exception as e:
            await message.answer(f"❌ Search error: {e}")

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

        # Dispatch in-process (dost.dost module was removed; shell-outs are broken)
        try:
            result = dispatch_prompt_to_fleet(prompt)
            if result.get("ok"):
                task_id = result.get("task_id", "unknown")
                agent_id = result.get("agent_id", "unknown")
                await message.answer(
                    f"✅ *Dispatched*\n"
                    f"Task: `{task_id}`\n"
                    f"Agent: `{agent_id}`"
                )
            else:
                await message.answer(f"❌ Dispatch failed: {result.get('error', 'unknown')}")
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
            BotCommand(command="search", description="Search the web"),
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
            text = generate_daily_briefing()
            await self.send_message(f"📈 *Daily Briefing*\n\n{text[:3500]}")
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