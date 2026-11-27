"""Fleet Self-Healing for Dost.

Monitors fleet health and automatically recovers from common issues:
- Stuck task detection and re-dispatch
- Provider pool saturation and auto-failover
- Error rate spikes and circuit breaking
- Stuck service restart via launchctl

All remediation is paper/testnet-only: restarting a dost service or
re-dispatching a task never places live orders and never touches credentials.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `import ops`)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # AI-Office/ (for `from dost.dost_main`)

from memory_pkg.unified import get_unified_memory

from dost.dost_main import dispatch_prompt_to_fleet


HEALING_CONFIG = {
    "enabled": True,
    "check_interval_sec": 60,
    "thresholds": {
        "task_stuck_minutes": 30,      # Task stuck if no update for 30 min
        "pool_saturation_pct": 85,     # Failover if pool >85% saturated
        "error_rate_pct": 10,          # Circuit break if error rate >10%
        "max_retries": 3,              # Max re-dispatch attempts per task
        "cooldown_sec": 300,           # 5 min between same actions
    },
    "delivery_channels": ["telegram", "web", "memory"],
}

# dost launchd service labels that FleetSelfHealing may restart during remediation.
# Paper/testnet-only: restarting a dost service never places live orders.
SERVICE_LABELS = {
    "proactive_agent": "com.aryan.dost-proactive-agent",
    "office_web": "com.aryan.dost-office-web",
    "telegram_bot": "dev.krisharyanagarwal.dost-telegram-bot",
    "monitor": "com.aryan.dost-monitor",
}

# Hive task directory where dispatch_prompt_to_fleet writes pending task files.
HIVE_DIR = Path(__file__).resolve().parents[2] / "packages" / "office-os" / "tasks"

# Statuses considered eligible for automatic re-dispatch.
_REDISPATCHABLE_STATUSES = {"failed", "in_progress", "assigned"}


@dataclass
class HealingAction:
    """Record of a self-healing action taken."""

    id: str
    action_type: str  # stuck_task_redispatch, pool_failover, pool_recover, circuit_break, circuit_recover, service_restart
    target: str       # task_id, pool_name, service_label, etc.
    reason: str
    timestamp: str
    success: bool
    details: dict = field(default_factory=dict)


class FleetSelfHealing:
    """Self-healing system for fleet operations."""

    def __init__(self, config: dict | None = None):
        self.config = {**HEALING_CONFIG, **(config or {})}
        self.memory = get_unified_memory()
        self._last_action: dict[str, float] = {}
        self._action_history: list[HealingAction] = []
        # Pools currently failed over (routing preference switched). Persisted so the
        # web dashboard and watchdog can observe remediation state across restarts.
        self._failed_over_pools: set[str] = set(
            self.memory.get_preference("failed_over_pools", []) or []
        )
        # Circuit breaker state: True when dispatching is paused due to error spikes.
        self._circuit_broken: bool = False
        # Per-service heartbeat/health snapshots for the /health/ops dashboard.
        self._service_heartbeats: dict[str, dict] = (
            self.memory.get_preference("service_heartbeats", {}) or {}
        )

    # ----------------------- Metrics / task fetching -----------------------

    def fetch_fleet_metrics(self) -> dict[str, Any]:
        """Fetch current fleet metrics from web server."""
        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 "import urllib.request, json; "
                 "r = urllib.request.urlopen('http://127.0.0.1:8083/metrics', timeout=5); "
                 "print(json.dumps(json.load(r)))"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return {}
        except Exception as e:
            print(f"[self_healing] Failed to fetch metrics: {e}")
            return {}

    def fetch_task_status(self, task_id: str) -> dict[str, Any]:
        """Fetch status of a specific task from hive."""
        try:
            task_path = HIVE_DIR / f"{task_id}.json"
            if task_path.exists():
                return json.loads(task_path.read_text())
            return {}
        except Exception:
            return {}

    # ----------------------- Remediation actions -----------------------

    def _restart_service(self, service_label: str) -> HealingAction:
        """Restart a dost launchd service by label.

        Paper/testnet-only: restarting a dost service never places live orders.
        Tries `launchctl restart` first; falls back to `launchctl kickstart -p`
        for services that are not currently loaded.
        """
        now = datetime.now(timezone.utc).isoformat()
        detail: dict[str, Any] = {"service": service_label}
        success = False

        try:
            result = subprocess.run(
                ["launchctl", "restart", service_label],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode == 0:
                success = True
                detail.update(restarted=True, stdout=result.stdout.strip(), stderr=result.stderr.strip())
            else:
                detail.update(restarted=False, restart_rc=result.returncode,
                              restart_stderr=result.stderr.strip())
                # Service may not be loaded; try to (re)start it via kickstart.
                kick = subprocess.run(
                    ["launchctl", "kickstart", "-p", service_label],
                    capture_output=True, text=True, timeout=20,
                )
                detail.update(kickstarted=kick.returncode == 0,
                              kickstart_stdout=kick.stdout.strip(),
                              kickstart_stderr=kick.stderr.strip())
                success = kick.returncode == 0
        except Exception as e:
            detail.update(error=str(e), restarted=False)
            success = False

        self._record_heartbeat(service_label, "healthy" if success else "unhealthy",
                               error=None if success else detail.get("error") or detail.get("restart_stderr"))

        action = HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="service_restart",
            target=service_label,
            reason=f"Restart service {service_label} due to health failure",
            timestamp=now,
            success=success,
            details=detail,
        )
        print(f"[self_healing] Service restart {service_label}: {'ok' if success else 'failed'}")
        return action

    def _clear_task_backlog(self, metrics: dict) -> list[HealingAction]:
        """Re-dispatch stuck/failed hive tasks through the fleet.

        Scans HIVE_DIR for tasks that are stuck (in_progress/assigned with no
        update beyond task_stuck_minutes) or failed (under max_retries), and
        re-dispatches them via dispatch_prompt_to_fleet. Paper/testnet-only.
        """
        actions: list[HealingAction] = []
        stuck_minutes = self.config["thresholds"]["task_stuck_minutes"]
        max_retries = self.config["thresholds"]["max_retries"]
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)

        try:
            task_files = sorted(HIVE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except Exception:
            task_files = []

        for task_path in task_files:
            try:
                task = json.loads(task_path.read_text())
            except Exception:
                continue

            status = task.get("status")
            if status not in _REDISPATCHABLE_STATUSES:
                continue

            task_id = task.get("id")
            if not task_id:
                continue

            # Determine whether this task is eligible for re-dispatch.
            eligible = False
            updated_at = task.get("updated_at", "")
            if status in ("in_progress", "assigned") and updated_at:
                try:
                    updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if updated < cutoff:
                        eligible = True
                except Exception:
                    eligible = True
            elif status == "failed":
                retry_count = (task.get("metadata") or {}).get("redispatch_count", 0)
                if retry_count < max_retries:
                    eligible = True

            if not eligible:
                continue

            # Per-task cooldown.
            action_key = f"stuck_task_{task_id}"
            if not self._should_act(action_key):
                continue

            prompt = task.get("description", "")
            agent_id = task.get("agent_id") or "strategy-advisor"
            priority = task.get("priority", "normal")

            result = dispatch_prompt_to_fleet(prompt, agent_id=agent_id, priority=priority, dry_run=False)

            retry_count = (task.get("metadata") or {}).get("redispatch_count", 0) + 1
            try:
                task["metadata"] = task.get("metadata") or {}
                task["metadata"]["redispatch_count"] = retry_count
                task["metadata"]["last_redispatch_at"] = datetime.now(timezone.utc).isoformat()
                task["status"] = "redispatched"
                task["updated_at"] = datetime.now(timezone.utc).isoformat()
                task_path.write_text(json.dumps(task, indent=2))
            except Exception as e:
                print(f"[self_healing] Failed to mark task {task_id} redispatched: {e}")

            success = bool(result.get("ok"))
            action = HealingAction(
                id=f"heal-{int(time.time())}",
                action_type="stuck_task_redispatch",
                target=task_id,
                reason=f"Re-dispatched {status} task (attempt {retry_count}/{max_retries})",
                timestamp=datetime.now(timezone.utc).isoformat(),
                success=success,
                details={
                    "task_id": task_id,
                    "old_status": status,
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "new_task_id": result.get("task_id"),
                    "error": result.get("error"),
                    "prompt_preview": prompt[:120],
                },
            )
            actions.append(action)
            print(f"[self_healing] Re-dispatched task {task_id}: {'ok' if success else 'failed'}")

        return actions

    def _failover_pool(self, pool_name: str, saturation: float) -> HealingAction:
        """Trigger failover for a saturated pool and persist routing preference."""
        self._failed_over_pools.add(pool_name)
        self.memory.set_preference("failed_over_pools", sorted(self._failed_over_pools))
        now = datetime.now(timezone.utc).isoformat()
        action = HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="pool_failover",
            target=pool_name,
            reason=f"Pool saturated at {saturation:.1f}%; switched routing preference",
            timestamp=now,
            success=True,
            details={"pool": pool_name, "saturation": saturation},
        )
        self._record_heartbeat(pool_name, "degraded", error=None)
        print(f"[self_healing] Pool failover triggered for {pool_name}")
        return action

    def _recover_pool(self, pool_name: str, saturation: float) -> HealingAction:
        """Resume routing to a previously failed-over pool once it recovers."""
        self._failed_over_pools.discard(pool_name)
        self.memory.set_preference("failed_over_pools", sorted(self._failed_over_pools))
        now = datetime.now(timezone.utc).isoformat()
        action = HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="pool_recover",
            target=pool_name,
            reason=f"Pool {pool_name} recovered at {saturation:.1f}% saturation",
            timestamp=now,
            success=True,
            details={"pool": pool_name, "saturation": saturation},
        )
        self._record_heartbeat(pool_name, "healthy", error=None)
        print(f"[self_healing] Pool recovered: {pool_name}")
        return action

    def _record_heartbeat(self, service: str, status: str, error: Optional[str] = None) -> None:
        """Update a per-service heartbeat snapshot for the /health/ops dashboard."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self._service_heartbeats.get(service, {})
        entry["status"] = status
        entry["last_run"] = now
        if error:
            entry["error_count"] = entry.get("error_count", 0) + 1
            entry["last_error"] = error
        else:
            # Clear stale error once the service reports healthy again.
            entry.pop("last_error", None)
        self._service_heartbeats[service] = entry

    # ----------------------- Checks -----------------------

    def check_stuck_tasks(self, metrics: dict) -> list[HealingAction]:
        """Detect and re-dispatch stuck/failed tasks from the hive backlog."""
        return self._clear_task_backlog(metrics)

    def check_pool_saturation(self, metrics: dict) -> list[HealingAction]:
        """Check for provider pool saturation and trigger failover/recovery."""
        actions: list[HealingAction] = []
        pools = metrics.get("provider_pools", {})
        threshold = self.config["thresholds"]["pool_saturation_pct"]

        for pool_name, pool_data in pools.items():
            if not isinstance(pool_data, dict):
                continue
            available = pool_data.get("available", 0)
            total = pool_data.get("total", 1)
            if total > 0:
                saturation = (1 - available / total) * 100
                if saturation > threshold:
                    if pool_name in self._failed_over_pools:
                        continue  # already failed over
                    if self._should_act(f"pool_failover_{pool_name}"):
                        actions.append(self._failover_pool(pool_name, saturation))
                elif saturation < threshold - 10 and pool_name in self._failed_over_pools:
                    if self._should_act(f"pool_recover_{pool_name}"):
                        actions.append(self._recover_pool(pool_name, saturation))

        return actions

    def check_error_rates(self, metrics: dict) -> list[HealingAction]:
        """Check for error rate spikes and trigger circuit breaking/recovery."""
        actions: list[HealingAction] = []
        jev = metrics.get("jev", {})
        error_rate = jev.get("error_rate", 0)
        threshold = self.config["thresholds"]["error_rate_pct"]

        if error_rate > threshold:
            if self._should_act("circuit_break"):
                self._circuit_broken = True
                action = HealingAction(
                    id=f"heal-{int(time.time())}",
                    action_type="circuit_break",
                    target="fleet_dispatch",
                    reason=f"Error rate spike: {error_rate:.1f}%",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    success=True,
                    details={"error_rate": error_rate, "threshold": threshold},
                )
                actions.append(action)
        elif error_rate < threshold / 2 and self._circuit_broken:
            self._circuit_broken = False
            if self._should_act("circuit_recover"):
                action = HealingAction(
                    id=f"heal-{int(time.time())}",
                    action_type="circuit_recover",
                    target="fleet_dispatch",
                    reason=f"Error rate recovered: {error_rate:.1f}%",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    success=True,
                    details={"error_rate": error_rate, "threshold": threshold},
                )
                actions.append(action)

        return actions

    def check_service_health(self, metrics: dict) -> list[HealingAction]:
        """Check whether configured dost services are running; restart if not."""
        actions: list[HealingAction] = []
        for service_name, service_label in SERVICE_LABELS.items():
            try:
                result = subprocess.run(
                    ["launchctl", "list", service_label],
                    capture_output=True, text=True, timeout=10,
                )
                running = result.returncode == 0 and "PID" in result.stdout
            except Exception:
                running = False

            if not running:
                if self._should_act(f"service_restart_{service_name}"):
                    actions.append(self._restart_service(service_label))

        return actions

    # ----------------------- Cooldown / alerts / persistence -----------------------

    def _should_act(self, action_key: str) -> bool:
        """Check if enough time has passed since last action of this type."""
        now = time.time()
        last = self._last_action.get(action_key, 0)
        if now - last >= self.config["thresholds"]["cooldown_sec"]:
            self._last_action[action_key] = now
            return True
        return False

    async def _send_healing_alert(self, action: HealingAction) -> None:
        """Send a healing-action alert via Telegram when configured."""
        if "telegram" not in self.config["delivery_channels"]:
            return
        try:
            from telegram.bot import DostTelegramBot
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                bot = DostTelegramBot(token, int(chat_id))
                await bot.send_message(
                    f"🔧 *Self-Healing: {action.action_type}*\n"
                    f"Target: `{action.target}`\n"
                    f"Reason: {action.reason}\n"
                    f"Success: {action.success}"
                )
        except Exception as e:
            print(f"[self_healing] Telegram healing alert failed: {e}")

    def _log_action(self, action: HealingAction) -> None:
        """Log healing action to memory."""
        self.memory.add_message(
            "self_healing",
            "system",
            f"Healing action: {action.action_type} on {action.target} - {action.reason}",
            {"action": action.__dict__},
        )

    async def run_once(self) -> dict[str, Any]:
        """Run one self-healing cycle."""
        if not self.config["enabled"]:
            return {"ok": True, "actions": []}

        metrics = self.fetch_fleet_metrics()
        if not metrics:
            return {"ok": False, "error": "Failed to fetch metrics"}

        all_actions: list[HealingAction] = []

        # Run all checks
        all_actions.extend(self.check_stuck_tasks(metrics))
        all_actions.extend(self.check_pool_saturation(metrics))
        all_actions.extend(self.check_error_rates(metrics))
        all_actions.extend(self.check_service_health(metrics))

        # Record actions, alert, persist
        for action in all_actions:
            self._action_history.append(action)
            self._log_action(action)
            await self._send_healing_alert(action)

        # Store in memory for web dashboard (/health/ops)
        self.memory.set_preference("last_healing_actions", [
            {
                "id": a.id,
                "type": a.action_type,
                "target": a.target,
                "reason": a.reason,
                "timestamp": a.timestamp,
                "success": a.success,
            }
            for a in self._action_history[-50:]
        ])
        self.memory.set_preference("failed_over_pools", sorted(self._failed_over_pools))
        self.memory.set_preference("service_heartbeats", self._service_heartbeats)

        return {
            "ok": True,
            "actions": [
                {
                    "type": a.action_type,
                    "target": a.target,
                    "reason": a.reason,
                    "success": a.success,
                }
                for a in all_actions
            ],
        }

    async def run_loop(self):
        """Run continuous self-healing loop."""
        print(f"[self_healing] Starting loop (interval: {self.config['check_interval_sec']}s)")
        while True:
            try:
                result = await self.run_once()
                if not result.get("ok"):
                    print(f"[self_healing] Check failed: {result.get('error')}")
                elif result.get("actions"):
                    print(f"[self_healing] Actions taken: {len(result['actions'])}")
            except Exception as e:
                print(f"[self_healing] Loop error: {e}")
            time.sleep(self.config["check_interval_sec"])

    def get_healing_history(self, limit: int = 50) -> list[dict]:
        """Get recent healing actions."""
        return [
            {
                "id": a.id,
                "type": a.action_type,
                "target": a.target,
                "reason": a.reason,
                "timestamp": a.timestamp,
                "success": a.success,
                "details": a.details,
            }
            for a in self._action_history[-limit:]
        ]


async def main():
    """Entry point for running self-healing loop."""
    healing = FleetSelfHealing()
    print(f"[self_healing] Starting loop (interval: {healing.config['check_interval_sec']}s)")
    while True:
        try:
            result = await healing.run_once()
            if not result.get("ok"):
                print(f"[self_healing] Check failed: {result.get('error')}")
            elif result.get("actions"):
                print(f"[self_healing] Actions taken: {len(result['actions'])}")
        except Exception as e:
            print(f"[self_healing] Loop error: {e}")
        time.sleep(healing.config["check_interval_sec"])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
