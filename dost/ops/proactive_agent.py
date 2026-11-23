"""Unified Proactive Agent Runner for Dost.

Starts all proactive services as a single background process:
- Proactive Scheduler (cron/interval jobs)
- Anomaly Watch (continuous monitoring)
- Opportunity Scanner (hourly scans)
- Self-Healing (stuck task recovery, pool failover)

Can be run directly or installed as a launchd service.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.proactive_scheduler import ProactiveScheduler
from ops.anomaly_watch import AnomalyWatch
from ops.opportunity_scanner import OpportunityScanner
from ops.self_healing import FleetSelfHealing


class ProactiveAgent:
    """Unified runner for all proactive Dost services."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}
        self.logger = self._setup_logging()
        self.running = False
        self.tasks: list[asyncio.Task] = []

        # Initialize services
        self.scheduler = ProactiveScheduler(self.config.get("scheduler"))
        self.anomaly_watch = AnomalyWatch(self.config.get("anomaly_watch"))
        self.opportunity_scanner = OpportunityScanner(self.config.get("opportunity_scanner"))
        self.self_healing = FleetSelfHealing(self.config.get("self_healing"))

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("dost.proactive_agent")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    async def start(self) -> None:
        """Start all proactive services."""
        if self.running:
            self.logger.warning("Proactive agent already running")
            return

        self.logger.info("Starting Dost Proactive Agent...")
        self.running = True

        # Start scheduler (runs in background thread)
        if self.scheduler.start():
            self.logger.info("Proactive scheduler started")
        else:
            self.logger.warning("Scheduler failed to start (apscheduler not available)")

        # Create async tasks for each service loop
        self.tasks = [
            asyncio.create_task(self._run_anomaly_watch()),
            asyncio.create_task(self._run_opportunity_scanner()),
            asyncio.create_task(self._run_self_healing()),
        ]

        # Schedule morning briefing if enabled
        if self.config.get("morning_briefing", {}).get("enabled", True):
            self.tasks.append(asyncio.create_task(self._run_morning_briefing()))

        self.logger.info(f"Proactive agent started with {len(self.tasks)} background tasks")

        # Wait for all tasks
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            self.logger.info("Tasks cancelled")
        except Exception as e:
            self.logger.error(f"Error in proactive agent: {e}")
            raise

    async def _run_anomaly_watch(self) -> None:
        """Run anomaly watch loop."""
        self.logger.info("Starting anomaly watch loop")
        try:
            await self.anomaly_watch.run_loop()
        except asyncio.CancelledError:
            self.logger.info("Anomaly watch cancelled")
        except Exception as e:
            self.logger.error(f"Anomaly watch error: {e}")

    async def _run_opportunity_scanner(self) -> None:
        """Run opportunity scanner loop."""
        self.logger.info("Starting opportunity scanner loop")
        try:
            await self.opportunity_scanner.run_loop()
        except asyncio.CancelledError:
            self.logger.info("Opportunity scanner cancelled")
        except Exception as e:
            self.logger.error(f"Opportunity scanner error: {e}")

    async def _run_self_healing(self) -> None:
        """Run self-healing loop."""
        self.logger.info("Starting self-healing loop")
        try:
            await self.self_healing.run_loop()
        except asyncio.CancelledError:
            self.logger.info("Self-healing cancelled")
        except Exception as e:
            self.logger.error(f"Self-healing error: {e}")

    async def _run_morning_briefing(self) -> None:
        """Run morning briefing at scheduled time (handled by scheduler)."""
        # This is a placeholder - actual briefing is triggered by scheduler
        # The scheduler runs MorningBriefing as a cron job
        self.logger.info("Morning briefing scheduled via cron (06:00 UTC)")
        # Keep alive
        while self.running:
            await asyncio.sleep(3600)

    def stop(self) -> None:
        """Stop all services gracefully."""
        self.logger.info("Stopping proactive agent...")
        self.running = False

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Stop scheduler
        self.scheduler.stop()

        self.logger.info("Proactive agent stopped")


async def main():
    """Entry point for running the proactive agent."""
    import os

    # Default configuration
    config = {
        "scheduler": {
            "enabled": True,
            "jobs": {
                "morning_briefing": {"enabled": True, "trigger": "cron", "hour": 6, "minute": 0, "timezone": "UTC"},
                "anomaly_watch": {"enabled": True, "trigger": "interval", "seconds": 60},
                "opportunity_scanner": {"enabled": True, "trigger": "interval", "seconds": 3600},
            },
        },
        "anomaly_watch": {
            "enabled": True,
            "check_interval_sec": 60,
        },
        "opportunity_scanner": {
            "enabled": True,
            "schedule_interval_sec": 3600,
        },
        "self_healing": {
            "enabled": True,
            "check_interval_sec": 60,
        },
        "morning_briefing": {"enabled": True},
    }

    # Override from environment if needed
    if os.environ.get("DOST_PROACTIVE_CONFIG"):
        import json
        config.update(json.loads(os.environ["DOST_PROACTIVE_CONFIG"]))

    agent = ProactiveAgent(config)

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.stop()))

    try:
        await agent.start()
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()


if __name__ == "__main__":
    asyncio.run(main())