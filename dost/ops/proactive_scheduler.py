"""Proactive Scheduler for Dost.

Runs scheduled jobs using APScheduler:
- Morning briefing at 06:00 UTC
- Anomaly watch every 60s
- Opportunity scanner every 3600s
- Custom cron jobs from office.json
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import get_unified_memory


SCHEDULER_CONFIG = {
    "enabled": True,
    "jobs": {
        "morning_briefing": {
            "enabled": True,
            "trigger": "cron",
            "hour": 6,
            "minute": 0,
            "timezone": "UTC",
        },
        "anomaly_watch": {
            "enabled": True,
            "trigger": "interval",
            "seconds": 60,
        },
        "opportunity_scanner": {
            "enabled": True,
            "trigger": "interval",
            "seconds": 3600,
        },
    },
}


class ProactiveScheduler:
    """Manages scheduled proactive jobs for Dost."""

    def __init__(self, config: dict | None = None):
        self.config = {**SCHEDULER_CONFIG, **(config or {})}
        self.memory = get_unified_memory()
        self.scheduler: Optional[BackgroundScheduler] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        if not APSCHEDULER_AVAILABLE:
            print("[proactive_scheduler] WARNING: apscheduler not installed. Run: pip install apscheduler")

    def _load_config_from_office_json(self) -> dict:
        """Load scheduler config from office.json."""
        try:
            office_json = Path(__file__).resolve().parents[2] / "packages" / "office-os" / "config" / "office.json"
            if office_json.exists():
                office_cfg = json.loads(office_json.read_text())
                scheduler_cfg = office_cfg.get("scheduler", {})
                if scheduler_cfg:
                    return {**SCHEDULER_CONFIG, **scheduler_cfg}
        except Exception:
            pass
        return self.config

    def _job_morning_briefing(self):
        """Morning briefing job."""
        print("[scheduler] Running morning briefing job...")
        try:
            from ops.morning_briefing import MorningBriefing
            briefing = MorningBriefing()
            # Run sync version for scheduler
            import asyncio
            asyncio.run(briefing.run())
        except Exception as e:
            print(f"[scheduler] Morning briefing failed: {e}")

    def _job_anomaly_watch(self):
        """Anomaly watch job."""
        print("[scheduler] Running anomaly watch job...")
        try:
            from ops.anomaly_watch import AnomalyWatch
            watch = AnomalyWatch()
            import asyncio
            asyncio.run(watch.run_once())
        except Exception as e:
            print(f"[scheduler] Anomaly watch failed: {e}")

    def _job_opportunity_scanner(self):
        """Opportunity scanner job."""
        print("[scheduler] Running opportunity scanner job...")
        try:
            from ops.opportunity_scanner import OpportunityScanner
            scanner = OpportunityScanner()
            import asyncio
            asyncio.run(scanner.run_once())
        except Exception as e:
            print(f"[scheduler] Opportunity scanner failed: {e}")

    def start(self) -> bool:
        """Start the scheduler."""
        if not APSCHEDULER_AVAILABLE:
            print("[scheduler] Cannot start: apscheduler not available")
            return False

        if self._running:
            print("[scheduler] Already running")
            return True

        # Load config
        full_config = self._load_config_from_office_json()
        jobs = full_config.get("jobs", {})

        # Create scheduler
        self.scheduler = BackgroundScheduler(timezone=timezone.utc)

        # Add jobs
        job_map = {
            "morning_briefing": self._job_morning_briefing,
            "anomaly_watch": self._job_anomaly_watch,
            "opportunity_scanner": self._job_opportunity_scanner,
        }

        for job_name, job_config in jobs.items():
            if not job_config.get("enabled", True):
                continue

            func = job_map.get(job_name)
            if not func:
                print(f"[scheduler] Unknown job: {job_name}")
                continue

            trigger_cfg = job_config.get("trigger", "interval")
            if trigger_cfg == "cron":
                trigger = CronTrigger(
                    hour=job_config.get("hour", 6),
                    minute=job_config.get("minute", 0),
                    timezone=job_config.get("timezone", "UTC"),
                )
            elif trigger_cfg == "interval":
                trigger = IntervalTrigger(seconds=job_config.get("seconds", 3600))
            else:
                print(f"[scheduler] Unknown trigger type: {trigger_cfg}")
                continue

            self.scheduler.add_job(
                func,
                trigger,
                id=job_name,
                name=job_name.replace("_", " ").title(),
                max_instances=1,
                coalesce=True,
            )
            print(f"[scheduler] Added job: {job_name} ({trigger_cfg})")

        # Start scheduler
        self.scheduler.start()
        self._running = True
        print("[scheduler] Started")

        # Register shutdown handler
        signal.signal(signal.SIGTERM, self._shutdown_handler)
        signal.signal(signal.SIGINT, self._shutdown_handler)

        return True

    def _shutdown_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"[scheduler] Received signal {signum}, shutting down...")
        self.stop()

    def stop(self):
        """Stop the scheduler."""
        if self.scheduler and self._running:
            self.scheduler.shutdown(wait=True)
            self._running = False
            print("[scheduler] Stopped")

    def get_job_status(self) -> dict[str, Any]:
        """Get status of all jobs."""
        if not self.scheduler:
            return {"running": False, "jobs": {}}

        jobs_info = {}
        for job in self.scheduler.get_jobs():
            jobs_info[job.id] = {
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }

        return {
            "running": self._running,
            "jobs": jobs_info,
        }

    def run_forever(self):
        """Block until shutdown."""
        if not self._running:
            self.start()

        try:
            while self._running:
                time.sleep(60)
        except KeyboardInterrupt:
            self.stop()


def main():
    """Entry point for running scheduler."""
    scheduler = ProactiveScheduler()
    scheduler.run_forever()


if __name__ == "__main__":
    main()