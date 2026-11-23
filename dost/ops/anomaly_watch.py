"""Anomaly Detection for Dost.

Monitors fleet metrics and detects anomalies:
- Cost burn rate spikes
- Provider pool saturation
- Error rate anomalies
- Drawdown alerts
- Task queue backlogs
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import get_unified_memory


ANOMALY_CONFIG = {
    "enabled": True,
    "check_interval_sec": 60,
    "thresholds": {
        "cost_burn_pct_per_hour": 10,      # Alert if >10% of daily cap per hour
        "pool_saturation_pct": 80,         # Alert if pool >80% saturated
        "error_rate_pct": 5,               # Alert if error rate >5%
        "queue_backlog_tasks": 100,        # Alert if >100 tasks pending
        "drawdown_pct": 5,                 # Alert if portfolio drawdown >5%
    },
    "cooldown_sec": 300,  # 5 min between same-type alerts
    "delivery_channels": ["telegram", "web"],
}


class AnomalyWatch:
    """Monitors fleet for anomalies and sends alerts."""

    def __init__(self, config: dict | None = None):
        self.config = config or ANOMALY_CONFIG
        self.memory = get_unified_memory()
        self._last_alert: dict[str, float] = {}

    def fetch_metrics(self) -> dict[str, Any]:
        """Fetch current fleet metrics from web server."""
        try:
            result = subprocess.run(
                [sys.executable, "-c", "import urllib.request; import json; r = urllib.request.urlopen('http://localhost:8083/api/metrics', timeout=5); print(json.dumps(json.load(r)))"],  # noqa: E501
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return {}
        except Exception:
            return {}

    def check_cost_burn(self, metrics: dict) -> Optional[dict]:
        """Check for cost burn rate anomaly."""
        # Get daily cost cap from office.json
        try:
            office_json = Path(__file__).resolve().parents[2] / "packages" / "office-os" / "config" / "office.json"
            if office_json.exists():
                office_cfg = json.loads(office_json.read_text())
                cap = (office_cfg.get("cost_cap") or {}).get("daily_units", 5000)
            else:
                cap = 5000
        except Exception:
            cap = 5000

        # Get current cost from billing
        try:
            from billing.meter import get_current_month_cost
            current_cost = get_current_month_cost()
        except Exception:
            current_cost = 0

        # Estimate hourly burn (simplified)
        # In production, would track cost over time
        threshold = cap * (self.config["thresholds"]["cost_burn_pct_per_hour"] / 100)
        if current_cost > threshold:
            return {
                "type": "cost_burn",
                "severity": "high",
                "message": f"Cost burn rate high: {current_cost}/{cap} units used",
                "current": current_cost,
                "cap": cap,
                "threshold": threshold,
            }
        return None

    def check_pool_saturation(self, metrics: dict) -> Optional[dict]:
        """Check for provider pool saturation."""
        pools = metrics.get("provider_pools", {})
        for pool_name, pool_data in pools.items():
            if isinstance(pool_data, dict):
                available = pool_data.get("available", 0)
                total = pool_data.get("total", 1)
                if total > 0:
                    saturation = (1 - available / total) * 100
                    if saturation > self.config["thresholds"]["pool_saturation_pct"]:
                        return {
                            "type": "pool_saturation",
                            "severity": "high",
                            "message": f"Pool {pool_name} saturated: {saturation:.0f}%",
                            "pool": pool_name,
                            "saturation_pct": saturation,
                        }
        return None

    def check_error_rate(self, metrics: dict) -> Optional[dict]:
        """Check for error rate anomaly."""
        jev = metrics.get("jev", {})
        error_rate = jev.get("error_rate", 0)
        if error_rate > self.config["thresholds"]["error_rate_pct"]:
            return {
                "type": "error_rate",
                "severity": "high",
                "message": f"Error rate elevated: {error_rate:.1f}%",
                "error_rate": error_rate,
            }
        return None

    def check_queue_backlog(self, metrics: dict) -> Optional[dict]:
        """Check for task queue backlog."""
        jev = metrics.get("jev", {})
        pending = jev.get("pending_tasks", 0)
        if pending > self.config["thresholds"]["queue_backlog_tasks"]:
            return {
                "type": "queue_backlog",
                "severity": "medium",
                "message": f"Task queue backlog: {pending} pending",
                "pending": pending,
            }
        return None

    def check_drawdown(self, metrics: dict) -> Optional[dict]:
        """Check for portfolio drawdown (placeholder)."""
        # In production, would check trading portfolio
        return None

    def _should_alert(self, alert_type: str) -> bool:
        """Check if enough time has passed since last alert of this type."""
        now = time.time()
        last = self._last_alert.get(alert_type, 0)
        if now - last >= self.config["cooldown_sec"]:
            self._last_alert[alert_type] = now
            return True
        return False

    async def send_alert(self, alert: dict) -> bool:
        """Send alert via configured channels."""
        alert_type = alert["type"]
        if not self._should_alert(alert_type):
            return False

        # Add timestamp
        alert["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Send via Telegram
        if "telegram" in self.config["delivery_channels"]:
            try:
                from telegram.bot import DostTelegramBot
                token = os.environ.get("TELEGRAM_BOT_TOKEN")
                chat_id = os.environ.get("TELEGRAM_CHAT_ID")
                if token and chat_id:
                    bot = DostTelegramBot(token, int(chat_id))
                    await bot.send_anomaly_alert(
                        alert["type"].replace("_", " ").title(),
                        alert["message"],
                    )
            except Exception as e:
                print(f"[anomaly_watch] Telegram alert failed: {e}")

        # Store for web dashboard
        if "web" in self.config["delivery_channels"]:
            try:
                alerts = self.memory.get_preference("anomaly_alerts", [])
                alerts.append(alert)
                # Keep last 100 alerts
                alerts = alerts[-100:]
                self.memory.set_preference("anomaly_alerts", alerts)
            except Exception as e:
                print(f"[anomaly_watch] Web alert store failed: {e}")

        # Log to memory
        self.memory.add_message(
            "anomaly_watch",
            "system",
            f"Anomaly detected: {alert['type']} - {alert['message']}",
            alert,
        )

        return True

    async def run_once(self) -> dict[str, Any]:
        """Run one anomaly detection cycle."""
        if not self.config["enabled"]:
            return {"ok": True, "checks": [], "alerts": []}

        metrics = self.fetch_metrics()
        if not metrics:
            return {"ok": False, "error": "Failed to fetch metrics"}

        checks = []
        alerts = []

        # Run all checks
        check_methods = [
            self.check_cost_burn,
            self.check_pool_saturation,
            self.check_error_rate,
            self.check_queue_backlog,
            self.check_drawdown,
        ]

        for check in check_methods:
            alert = check(metrics)
            check_name = check.__name__.replace("check_", "")
            checks.append({"check": check_name, "alerted": alert is not None})
            if alert:
                alerts.append(alert)
                await self.send_alert(alert)

        return {
            "ok": True,
            "checks": checks,
            "alerts": alerts,
        }

    async def run_loop(self):
        """Run continuous anomaly detection loop."""
        print(f"[anomaly_watch] Starting loop (interval: {self.config['check_interval_sec']}s)")
        while True:
            try:
                result = await self.run_once()
                if not result.get("ok"):
                    print(f"[anomaly_watch] Check failed: {result.get('error')}")
            except Exception as e:
                print(f"[anomaly_watch] Loop error: {e}")
            time.sleep(self.config["check_interval_sec"])


async def main():
    """Entry point for running anomaly watch."""
    watch = AnomalyWatch()
    await watch.run_loop()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())