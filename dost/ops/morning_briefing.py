"""Morning Briefing Automation for Dost.

Runs at 06:00 UTC to generate and distribute daily market briefing.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `import ops`, `import memory_pkg`)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # AI-Office/ (for `from dost.dost_main import ...`)

from dost.dost_main import generate_daily_briefing
from memory_pkg.unified import get_unified_memory


BRIEFING_CONFIG = {
    "enabled": True,
    "schedule_utc": "06:00",
    "topics": ["market_overview", "top_movers", "earnings", "crypto", "alerts"],
    "delivery_channels": ["telegram", "voice", "web"],
    "max_length": 3500,
}


class MorningBriefing:
    """Generates and distributes morning market briefing."""

    def __init__(self, config: dict | None = None):
        self.config = config or BRIEFING_CONFIG
        self.memory = get_unified_memory()

    def generate_briefing(self) -> dict[str, Any]:
        """Generate morning briefing by dispatching to fleet."""
        try:
            content = generate_daily_briefing()
            return {
                "ok": True,
                "content": content,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def format_briefing(self, raw_briefing: str) -> str:
        """Format briefing for delivery."""
        lines = raw_briefing.split("\n")
        # Add header
        header = f"🌅 *Morning Briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n\n"
        formatted = header + "\n".join(lines)
        # Truncate if too long
        if len(formatted) > self.config["max_length"]:
            formatted = formatted[:self.config["max_length"]] + "\n\n... (truncated)"
        return formatted

    async def deliver_telegram(self, briefing: str) -> bool:
        """Send briefing via Telegram."""
        try:
            from telegram.bot import DostTelegramBot
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if not token or not chat_id:
                print("[morning_briefing] Telegram not configured")
                return False
            bot = DostTelegramBot(token, int(chat_id))
            await bot.send_message(briefing)
            return True
        except Exception as e:
            print(f"[morning_briefing] Telegram delivery failed: {e}")
            return False

    def deliver_voice(self, briefing: str) -> bool:
        """Queue briefing for voice delivery (next voice session)."""
        try:
            # Store in memory for voice to pick up
            self.memory.set_preference("pending_voice_briefing", briefing)
            self.memory.set_preference("pending_voice_briefing_ts", time.time())
            return True
        except Exception as e:
            print(f"[morning_briefing] Voice queue failed: {e}")
            return False

    def deliver_web(self, briefing: str) -> bool:
        """Store briefing for web dashboard."""
        try:
            self.memory.set_preference("pending_web_briefing", briefing)
            self.memory.set_preference("pending_web_briefing_ts", time.time())
            return True
        except Exception as e:
            print(f"[morning_briefing] Web queue failed: {e}")
            return False

    async def run(self) -> dict[str, Any]:
        """Run the full morning briefing workflow."""
        print("[morning_briefing] Starting morning briefing generation...")

        # Generate
        result = self.generate_briefing()
        if not result.get("ok"):
            print(f"[morning_briefing] Generation failed: {result.get('error')}")
            return {"ok": False, "error": result.get("error")}

        raw = result["content"]
        formatted = self.format_briefing(raw)

        # Deliver to configured channels
        results = {"generated": True, "delivered": {}}

        if "telegram" in self.config["delivery_channels"]:
            telegram_ok = await self.deliver_telegram(formatted)
            results["delivered"]["telegram"] = telegram_ok

        if "voice" in self.config["delivery_channels"]:
            voice_ok = self.deliver_voice(formatted)
            results["delivered"]["voice"] = voice_ok

        if "web" in self.config["delivery_channels"]:
            web_ok = self.deliver_web(formatted)
            results["delivered"]["web"] = web_ok

        # Log to memory
        self.memory.add_message(
            "morning_briefing",
            "system",
            f"Morning briefing generated: {len(formatted)} chars",
            {"topics": self.config["topics"], "channels": list(results["delivered"].keys())},
        )

        print(f"[morning_briefing] Complete. Delivered: {results['delivered']}")
        return {"ok": True, **results}


async def main():
    """Entry point for scheduled run."""
    briefing = MorningBriefing()
    result = await briefing.run()
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())