"""Opportunity Scanner for Dost.

Hourly scans for trading/research opportunities:
- Fundamental screens (value, quality, momentum)
- Technical signals (breakouts, mean reversion)
- Funding rate anomalies (perp basis)
- Governance proposals
- Earnings catalysts
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import get_unified_memory


SCANNER_CONFIG = {
    "enabled": True,
    "schedule_interval_sec": 3600,  # 1 hour
    "screens": {
        "fundamental_value": {"enabled": True, "min_score": 70},
        "fundamental_quality": {"enabled": True, "min_score": 70},
        "technical_breakout": {"enabled": True, "min_score": 60},
        "funding_rate_arb": {"enabled": True, "min_basis_bps": 20},
        "governance": {"enabled": True},
        "earnings_catalyst": {"enabled": True},
    },
    "max_opportunities": 10,
    "delivery_channels": ["telegram", "web"],
}


class OpportunityScanner:
    """Scans for trading/research opportunities."""

    def __init__(self, config: dict | None = None):
        self.config = config or SCANNER_CONFIG
        self.memory = get_unified_memory()

    def run_fundamental_screen(self, screen_name: str) -> list[dict]:
        """Run a fundamental screen via dost fleet."""
        prompt = f"Run {screen_name} fundamental screen on NIFTY50/US large caps. Return top 5 with scores and rationale."
        return self._dispatch_research(prompt, screen_name)

    def run_technical_screen(self) -> list[dict]:
        """Run technical breakout screen."""
        prompt = "Scan US large caps for technical breakouts: price > 20D high, volume > 1.5x avg, RSI 50-70. Return top 5."
        return self._dispatch_research(prompt, "technical_breakout")

    def run_funding_rate_scan(self) -> list[dict]:
        """Scan for funding rate arbitrage opportunities."""
        prompt = "Scan perp funding rates across major exchanges (Binance, Bybit, OKX). Find basis > 20bps annualized for major assets (BTC, ETH, SOL). Return opportunities."
        return self._dispatch_research(prompt, "funding_rate_arb")

    def run_governance_scan(self) -> list[dict]:
        """Scan for governance proposals."""
        prompt = "Check active governance proposals for major protocols (Uniswap, Aave, Compound, Maker, Lido). Flag any with >5% voter turnout or contentious votes."
        return self._dispatch_research(prompt, "governance")

    def run_earnings_scan(self) -> list[dict]:
        """Scan for upcoming earnings catalysts."""
        prompt = "List upcoming earnings for US large caps in next 7 days. Flag any with high options IV rank or historical post-earnings moves >5%."
        return self._dispatch_research(prompt, "earnings_catalyst")

    def _dispatch_research(self, prompt: str, screen_type: str) -> list[dict]:
        """Dispatch research task to fleet and parse results."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--dispatch", prompt, "--department", "research"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("ok"):
                    # Store task ID for tracking
                    return [{
                        "screen": screen_type,
                        "task_id": data.get("task_id"),
                        "agent": data.get("agent_id"),
                        "prompt": prompt[:200],
                        "status": "dispatched",
                    }]
            return [{"screen": screen_type, "error": result.stderr[:200], "status": "failed"}]
        except Exception as e:
            return [{"screen": screen_type, "error": str(e), "status": "failed"}]

    def synthesize_opportunities(self, all_results: list[dict]) -> str:
        """Synthesize scan results into readable summary."""
        lines = [
            f"🔍 *Opportunity Scan — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n",
        ]

        for result in all_results:
            screen = result.get("screen", "unknown")
            status = result.get("status", "unknown")
            if status == "dispatched":
                lines.append(f"✅ *{screen}*: Dispatched (task: {result.get('task_id', '?')})")
            else:
                lines.append(f"❌ *{screen}*: Failed - {result.get('error', 'unknown')}")

        lines.append(f"\n_Total screens: {len(all_results)}_")
        return "\n".join(lines)

    async def run_once(self) -> dict[str, Any]:
        """Run one full scan cycle."""
        if not self.config["enabled"]:
            return {"ok": True, "results": []}

        print("[opportunity_scanner] Starting opportunity scan...")

        all_results = []

        # Run enabled screens
        if self.config["screens"].get("fundamental_value", {}).get("enabled"):
            all_results.extend(self.run_fundamental_screen("value"))

        if self.config["screens"].get("fundamental_quality", {}).get("enabled"):
            all_results.extend(self.run_fundamental_screen("quality"))

        if self.config["screens"].get("technical_breakout", {}).get("enabled"):
            all_results.extend(self.run_technical_screen())

        if self.config["screens"].get("funding_rate_arb", {}).get("enabled"):
            all_results.extend(self.run_funding_rate_scan())

        if self.config["screens"].get("governance", {}).get("enabled"):
            all_results.extend(self.run_governance_scan())

        if self.config["screens"].get("earnings_catalyst", {}).get("enabled"):
            all_results.extend(self.run_earnings_scan())

        # Synthesize
        summary = self.synthesize_opportunities(all_results)

        # Store for web dashboard
        self.memory.set_preference("last_opportunity_scan", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": all_results,
            "summary": summary,
        })

        # Log to memory
        self.memory.add_message(
            "opportunity_scanner",
            "system",
            f"Opportunity scan complete: {len(all_results)} screens dispatched",
            {"screens": [r.get("screen") for r in all_results]},
        )

        # Deliver to channels
        delivered = {}
        if "telegram" in self.config["delivery_channels"]:
            try:
                from telegram.bot import DostTelegramBot
                token = os.environ.get("TELEGRAM_BOT_TOKEN")
                chat_id = os.environ.get("TELEGRAM_CHAT_ID")
                if token and chat_id:
                    bot = DostTelegramBot(token, int(chat_id))
                    await bot.send_message(summary)
                    delivered["telegram"] = True
            except Exception as e:
                print(f"[opportunity_scanner] Telegram delivery failed: {e}")

        if "web" in self.config["delivery_channels"]:
            delivered["web"] = True

        return {
            "ok": True,
            "results": all_results,
            "delivered": delivered,
        }

    async def run_loop(self):
        """Run continuous scanning loop."""
        print(f"[opportunity_scanner] Starting loop (interval: {self.config['schedule_interval_sec']}s)")
        while True:
            try:
                result = await self.run_once()
                if not result.get("ok"):
                    print(f"[opportunity_scanner] Scan failed: {result.get('error')}")
            except Exception as e:
                print(f"[opportunity_scanner] Loop error: {e}")
            time.sleep(self.config["schedule_interval_sec"])


async def main():
    """Entry point for running opportunity scanner."""
    import os
    scanner = OpportunityScanner()
    await scanner.run_loop()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())