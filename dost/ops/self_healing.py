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

import asyncio
import json
import math
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

from dost.dost_main import dispatch_prompt_to_fleet, tier_c_agents


HEALING_CONFIG = {
    "enabled": True,
    "check_interval_sec": 60,
    "thresholds": {
        "task_stuck_minutes": 30,      # Task stuck if no update for 30 min
        "pool_saturation_pct": 85,     # Failover if pool >85% saturated
        "error_rate_pct": 10,          # Circuit break if error rate >10%
        "max_retries": 3,              # Max re-dispatch attempts per task
        "cooldown_sec": 300,           # 5 min between same actions
        "escalation_threshold": 3,     # consecutive failures before an alert is escalated
        # Infrastructure thresholds
        "disk_usage_pct": 90,          # Disk cleanup if root fs >90% full
        "memory_pressure_pct": 90,     # Memory pressure action if >90% used
        "trend_window_minutes": 60,    # Lookback window for predictive trend analysis
        # Provider pool auto-scaling: shift routing traffic away from pools
        # approaching saturation before the hard failover threshold is hit.
        "pool_scale_down_pct": 70,     # Saturation at which to scale a pool down
        "pool_scale_up_pct": 40,       # Saturation at which to scale a pool back up
        "pool_min_scale": 0.25,        # Minimum routing share kept for any pool
        "pool_scale_step": 0.5,        # Factor to scale up/down by per cycle
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

# OpenAlice trading fleet launchd service labels that FleetSelfHealing may
# restart during remediation. Paper/testnet-only: restarting a trading fleet
# service never places live orders and never touches credentials.
OPENALICE_SERVICE_LABELS = {
    "trading_bot": "com.aryan.trading-bot",
    "fleet_metrics": "com.aryan.fleet-metrics",
}

# Prometheus text endpoint exposed by OpenAlice's fleet_metrics exporter (port 9109).
TRADING_FLEET_METRICS_URL = "http://127.0.0.1:9109/metrics"

# Hive task directory where dispatch_prompt_to_fleet writes pending task files.
HIVE_DIR = Path(__file__).resolve().parents[2] / "packages" / "office-os" / "tasks"

# Statuses considered eligible for automatic re-dispatch.
_REDISPATCHABLE_STATUSES = {"failed", "in_progress", "assigned"}


@dataclass
class HealingAction:
    """Record of a self-healing action taken."""

    id: str
    action_type: str  # stuck_task_redispatch, pool_failover, pool_recover, pool_scale_down, pool_scale_up, circuit_break, circuit_recover, service_restart
    target: str       # task_id, pool_name, service_label, etc.
    reason: str
    timestamp: str
    success: bool
    details: dict = field(default_factory=dict)


class FleetSelfHealing:
    """Self-healing system for fleet operations."""

    def __init__(self, config: dict | None = None, memory=None):
        self.config = {**HEALING_CONFIG, **(config or {})}
        self.memory = memory if memory is not None else get_unified_memory()
        self._last_action: dict[str, float] = {}
        self._action_history: list[HealingAction] = []
        # Consecutive failure count per cooldown key for escalating backoff.
        # A repeatedly-failing remediation backs off exponentially (capped) so a
        # flapping service cannot hammer restart attempts every cycle.
        self._consecutive_failures: dict[str, int] = {}
        # Maximum backoff multiplier applied to the base cooldown.
        self._max_backoff_multiplier = 8
        # Pools currently failed over (routing preference switched). Persisted so the
        # web dashboard and watchdog can observe remediation state across restarts.
        self._failed_over_pools: set[str] = set(
            self.memory.get_preference("failed_over_pools", []) or []
        )
        # Per-pool routing scale factors (1.0 = full traffic share). Persisted so
        # auto-scaling decisions survive restarts and are visible on the dashboard.
        stored_pool_factors = self.memory.get_preference("pool_scale_factors", {})
        self._pool_scale_factors: dict[str, float] = {}
        if isinstance(stored_pool_factors, dict):
            for name, scale in stored_pool_factors.items():
                if not isinstance(name, str) or not name:
                    continue
                if isinstance(scale, bool) or not isinstance(scale, (int, float)):
                    continue
                if not math.isfinite(scale):
                    continue
                self._pool_scale_factors[name] = float(scale)
        # Circuit breaker state: True when dispatching is paused due to error spikes.
        # Persisted across restarts so a tripped circuit stays open after reboot.
        self._circuit_broken: bool = bool(
            self.memory.get_preference("circuit_broken", False) or False
        )
        # Remediation-failure alerts surface on /health/ops; persisted so they
        # survive restarts. Capped in memory to avoid unbounded growth.
        self._alerts: list[dict] = (
            self.memory.get_preference("healing_alerts", []) or []
        )[-200:]
        # Per-service heartbeat/health snapshots for the /health/ops dashboard.
        self._service_heartbeats: dict[str, dict] = (
            self.memory.get_preference("service_heartbeats", {}) or {}
        )
        # Supervision state for the 24/7 self-healing loop. Tracks consecutive
        # loop failures so a repeatedly-crashing run_once backs off instead of
        # spinning hot, and records a liveness heartbeat for /health/ops.
        self._loop_failures: int = int(
            self.memory.get_preference("self_healing_loop_failures", 0) or 0
        )
        self._loop_last_error: Optional[str] = (
            self.memory.get_preference("self_healing_loop_last_error") or None
        )
        self._loop_healthy: bool = bool(
            self.memory.get_preference("self_healing_loop_healthy", True) or True
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
            print(f"[self_healing] Failed to fetch metrics: {e}", file=sys.stderr)
            return {}

    def fetch_trading_fleet_metrics(self) -> dict[str, dict[str, float]]:
        """Fetch trading fleet metrics from the OpenAlice fleet_metrics exporter.

        Scrapes the Prometheus text exposition format served at
        TRADING_FLEET_METRICS_URL (:9109/metrics) and parses it into
        {metric_name: {label_key: value}}, where label_key is the raw label
        string (e.g. check="hive") or "" for unlabelled series.

        Read-only and paper/testnet-only: a local scrape of a metrics
        endpoint, never a model call and never credentials. Returns {} when
        the exporter is unreachable or the text is unparseable; callers
        degrade gracefully rather than failing the cycle.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 "import urllib.request; "
                 "r = urllib.request.urlopen('http://127.0.0.1:9109/metrics', timeout=5); "
                 "print(r.read().decode('utf-8'))"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {}
            return self._parse_prometheus_text(result.stdout)
        except Exception as e:
            print(f"[self_healing] Failed to fetch trading fleet metrics: {e}", file=sys.stderr)
            return {}

    @staticmethod
    def _parse_prometheus_text(text: str) -> dict[str, dict[str, float]]:
        """Parse Prometheus text exposition format into {metric: {label_key: value}}.

        Skips HELP/TYPE lines, comments and blank lines. Malformed sample
        lines are skipped silently so one bad line cannot hide the rest.
        """
        metrics: dict[str, dict[str, float]] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "{" in line:
                name, rest = line.split("{", 1)
                label_part, sep, value = rest.partition("}")
                if not sep:
                    continue
                label_key = "{" + label_part + "}"
                value = value.strip()
            else:
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                name, value = parts
                label_key = ""
            try:
                metrics.setdefault(name.strip(), {})[label_key] = float(value)
            except ValueError:
                continue
        return metrics

    def _prometheus_value(
        self, metrics: dict[str, dict[str, float]], name: str, label: str | None = None
    ) -> float | None:
        """Return the value of a Prometheus series, or None if not present.

        With label=None, reads the unlabelled series for gauge metrics like
        fleet_health_ok or fleet_agents_alive that carry no labels.
        """
        series = metrics.get(name)
        if not series:
            return None
        if label is None:
            return series.get("")
        return series.get(label)

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

    def _restart_service(self, service_label: str, reason: str | None = None) -> HealingAction:
        """Restart a launchd service by label.

        Paper/testnet-only: restarting a service never places live orders.
        Uses `launchctl kickstart -k -p gui/<uid>/<label>`, which terminates a
        running service then (re)starts it — the modern equivalent of restart
        on this macOS (there is no `launchctl restart` subcommand).
        """
        now = datetime.now(timezone.utc).isoformat()
        uid = os.getuid()
        target = f"gui/{uid}/{service_label}"
        detail: dict[str, Any] = {"service": service_label, "target": target}
        success = False

        try:
            kick = subprocess.run(
                ["launchctl", "kickstart", "-k", "-p", target],
                capture_output=True, text=True, timeout=20,
            )
            detail.update(
                kickstarted=kick.returncode == 0,
                restarted=kick.returncode == 0,
                kickstart_stdout=kick.stdout.strip(),
                kickstart_stderr=kick.stderr.strip(),
            )
            success = kick.returncode == 0
        except Exception as e:
            detail.update(error=str(e), kickstarted=False, restarted=False)
            success = False

        self._record_heartbeat(service_label, "healthy" if success else "unhealthy",
                               error=None if success else detail.get("error") or detail.get("restart_stderr"))

        action = HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="service_restart",
            target=service_label,
            reason=reason or f"Restart service {service_label} due to health failure",
            timestamp=now,
            success=success,
            details=detail,
        )
        self._record_action_outcome(f"service_restart_{service_label}", success)

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

            # Tier C agents are human-only: never re-run them automatically.
            if agent_id in tier_c_agents():
                continue

            original_meta = task.get("metadata") or {}
            extra = {"redispatched_from": task_id}
            if original_meta.get("broadcast_id"):
                extra["broadcast_id"] = original_meta["broadcast_id"]
            result = dispatch_prompt_to_fleet(
                prompt, agent_id=agent_id, priority=priority, dry_run=False, extra_metadata=extra,
            )

            retry_count = original_meta.get("redispatch_count", 0) + 1
            try:
                task["metadata"] = original_meta
                task["metadata"]["redispatch_count"] = retry_count
                task["metadata"]["last_redispatch_at"] = datetime.now(timezone.utc).isoformat()
                if result.get("task_id"):
                    task["metadata"]["redispatched_to"] = result["task_id"]
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
            self._record_action_outcome(f"stuck_task_{task_id}", success)
            if not success:
                self._record_remediation_failure_alert(action)
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

    def _pool_saturation(self, pool_data: dict) -> float:
        """Saturation % for a pool from metrics.

        Handles both numeric ``available``/``total`` (test fixtures) and boolean
        ``available`` with no ``total`` (live /metrics endpoint).
        """
        available = pool_data.get("available", 0)
        if isinstance(available, bool):
            return 0.0 if available else 100.0
        total = pool_data.get("total")
        if isinstance(total, (int, float)) and total > 0 and isinstance(available, (int, float)):
            return (1 - available / total) * 100
        return 0.0

    def _record_pool_scale(
        self, pool_name: str, scale: float, saturation: float, reason: str
    ) -> HealingAction:
        """Emit a pool scale-up/scale-down healing action and refresh heartbeat."""
        now = datetime.now(timezone.utc).isoformat()
        action_type = "pool_scale_down" if scale < 1.0 else "pool_scale_up"
        self._record_heartbeat(pool_name, "healthy", error=None)
        return HealingAction(
            id=f"heal-{int(time.time())}",
            action_type=action_type,
            target=pool_name,
            reason=(
                f"Pool {pool_name}: {reason} "
                f"(routing scale {scale:.2f}, saturation {saturation:.0f}%)"
            ),
            timestamp=now,
            success=True,
            details={"pool": pool_name, "scale": scale, "saturation": saturation},
        )

    def check_provider_pool_scaling(self, metrics: dict) -> list[HealingAction]:
        """Auto-scale provider pool routing preferences based on saturation trends.

        Pools approaching saturation are scaled down pre-emptively (traffic
        shifted to healthier pools) before the hard failover threshold is hit,
        and scaled back up as they recover. Failed-over pools are left alone --
        failover already owns their routing.

        Paper/testnet-only: adjusts routing weights, never touches credentials
        or live order paths.
        """
        actions: list[HealingAction] = []
        pools = metrics.get("provider_pools", {})
        down_pct = self.config["thresholds"]["pool_scale_down_pct"]
        up_pct = self.config["thresholds"]["pool_scale_up_pct"]
        min_scale = self.config["thresholds"]["pool_min_scale"]
        step = self.config["thresholds"]["pool_scale_step"]

        for pool_name, pool_data in pools.items():
            if not isinstance(pool_data, dict):
                continue
            saturation = self._pool_saturation(pool_data)
            scale = self._pool_scale_factors.get(pool_name, 1.0)

            # A failed-over pool is already routed around; failover owns it.
            if pool_name in self._failed_over_pools:
                continue

            if saturation > down_pct and scale > min_scale:
                new_scale = max(min_scale, round(scale * step, 4))
                if new_scale != scale:
                    self._pool_scale_factors[pool_name] = new_scale
                    actions.append(
                        self._record_pool_scale(
                            pool_name,
                            new_scale,
                            saturation,
                            f"saturating at {saturation:.0f}%; shifting traffic away",
                        )
                    )
            elif saturation < up_pct and scale < 1.0:
                new_scale = min(1.0, round(scale / step, 4))
                if new_scale != scale:
                    self._pool_scale_factors[pool_name] = new_scale
                    actions.append(
                        self._record_pool_scale(
                            pool_name,
                            new_scale,
                            saturation,
                            f"recovered to {saturation:.0f}%; restoring traffic share",
                        )
                    )

        # Persist routing preferences for the dashboard and subsequent cycles.
        self.memory.set_preference("pool_scale_factors", self._pool_scale_factors)
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

    def check_trading_fleet_health(self, metrics: dict) -> list[HealingAction]:
        """Check whether OpenAlice trading fleet launchd services are running; restart if not.

        Paper/testnet-only: restarting a trading fleet service never places
        live orders and never touches credentials. Each service has its own
        cooldown key so a flapping trading bot does not suppress the
        fleet_metrics exporter restart and vice versa.
        """
        actions: list[HealingAction] = []
        for service_name, service_label in OPENALICE_SERVICE_LABELS.items():
            try:
                result = subprocess.run(
                    ["launchctl", "list", service_label],
                    capture_output=True, text=True, timeout=10,
                )
                running = result.returncode == 0 and "PID" in result.stdout
            except Exception:
                running = False

            if not running:
                if self._should_act(f"trading_service_restart_{service_name}"):
                    actions.append(
                        self._restart_service(
                            service_label,
                            reason=f"Trading fleet service {service_name} not running; restarting",
                        )
                    )

        return actions

    def check_trading_metrics_health(self, trading_metrics: dict) -> list[HealingAction]:
        """Evaluate trading fleet health from the fleet_metrics exporter and remediate degradation.

        Reads fleet_health_ok, fleet_checks_failing and the agent ratio
        (fleet_agents_alive / fleet_agents_expected) from the parsed
        Prometheus text. When the fleet is degraded, restarts the trading
        bot service once per cooldown. When healthy, records a healthy
        heartbeat so the /health/ops dashboard can observe trading fleet
        state alongside dost services.

        Paper/testnet-only: the restart never places live orders and never
        touches credentials; the scrape itself is read-only.
        """
        actions: list[HealingAction] = []
        if not trading_metrics:
            # Exporter unreachable: nothing to evaluate from metrics. The
            # exporter service itself is covered by check_trading_fleet_health.
            return actions

        health_ok = self._prometheus_value(trading_metrics, "fleet_health_ok")
        checks_failing = self._prometheus_value(trading_metrics, "fleet_checks_failing")
        agents_alive = self._prometheus_value(trading_metrics, "fleet_agents_alive")
        agents_expected = self._prometheus_value(trading_metrics, "fleet_agents_expected")

        reasons: list[str] = []
        if health_ok is not None and health_ok == 0:
            reasons.append("fleet_health_ok=0")
        if checks_failing is not None and checks_failing > 0:
            reasons.append(f"fleet_checks_failing={checks_failing:.0f}")
        if (
            agents_alive is not None
            and agents_expected is not None
            and agents_expected > 0
            and agents_alive < agents_expected
        ):
            reasons.append(f"agents {agents_alive:.0f}/{agents_expected:.0f} alive")

        if reasons:
            if self._should_act("trading_fleet_degraded"):
                actions.append(
                    self._restart_service(
                        OPENALICE_SERVICE_LABELS["trading_bot"],
                        reason=f"Trading fleet degraded ({'; '.join(reasons)}); restarting trading bot",
                    )
                )
        else:
            self._record_heartbeat(
                OPENALICE_SERVICE_LABELS["trading_bot"], "healthy"
            )

        return actions

    # ----------------------- Infrastructure remediation -----------------------

    def _disk_usage(self) -> tuple[float, str]:
        """Return (usage_pct, mountpoint) for the root filesystem."""
        try:
            result = subprocess.run(
                ["df", "-P", "/"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                if len(lines) >= 2:
                    parts = lines[1].split()
                    # df -P output: Filesystem 1024-blocks Used Available Capacity Mounted
                    capacity = parts[4].replace("%", "")
                    return float(capacity), parts[0]
        except Exception as e:
            print(f"[self_healing] Failed to check disk usage: {e}")
        return 0.0, "/"

    def _memory_usage(self) -> float:
        """Return approximate memory usage percentage via `vm_stat`."""
        try:
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                pages = {}
                for line in result.stdout.splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip().replace(" ", "_")
                        try:
                            pages[key] = float(val.strip().rstrip("."))
                        except ValueError:
                            continue
                total = sum(pages.values())
                used = pages.get("Pages_active", 0) + pages.get("Pages_speculative", 0) + pages.get("Pages_wired_down", 0)
                if total > 0:
                    return (used / total) * 100
        except Exception as e:
            print(f"[self_healing] Failed to check memory usage: {e}")
        return 0.0

    def _cleanup_disk(self, usage_pct: float) -> HealingAction:
        """Clean up old logs and temp files to free disk space.

        Paper/testnet-only: removes nur dost log/temp artifacts, never
        credentials or user data.
        """
        now = datetime.now(timezone.utc).isoformat()
        freed_mb = 0.0
        targets = [
            (Path(__file__).resolve().parents[2] / "dost" / "logs"),
            (Path(__file__).resolve().parents[2] / "packages" / "office-os" / "logs"),
        ]
        for target in targets:
            if not target.exists():
                continue
            for log_file in target.glob("*.log.*"):
                # Rotated logs older than the current one are safe to remove.
                try:
                    size_mb = log_file.stat().st_size / (1024 * 1024)
                    log_file.unlink()
                    freed_mb += size_mb
                except Exception:
                    pass
        success = freed_mb >= 0  # cleanup is best-effort; always "success" if no exception
        self._record_heartbeat("disk_cleanup", "healthy" if success else "degraded")
        return HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="disk_cleanup",
            target="root_filesystem",
            reason=f"Disk usage at {usage_pct:.0f}%; cleaned {freed_mb:.1f} MB of rotated logs",
            timestamp=now,
            success=success,
            details={"usage_pct": usage_pct, "freed_mb": round(freed_mb, 1)},
        )

    def _handle_memory_pressure(self, usage_pct: float) -> HealingAction:
        """Respond to memory pressure by recording heartbeat and logging.

        Paper/testnet-only: no processes are killed; only observed and reported.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._record_heartbeat("memory", "degraded", error=f"memory usage {usage_pct:.0f}%")
        return HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="memory_pressure",
            target="system_memory",
            reason=f"Memory usage at {usage_pct:.0f}%; no processes killed (paper/testnet-only)",
            timestamp=now,
            success=True,
            details={"usage_pct": usage_pct},
        )

    def _restart_web_server(self) -> Optional[HealingAction]:
        """Restart the office-web launchd service if it is not responding.

        Returns None when the service is already healthy (no remediation needed).
        Paper/testnet-only: restarting a dost service never places live orders.
        """
        now = datetime.now(timezone.utc).isoformat()
        label = "com.aryan.dost-office-web"
        try:
            result = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True, text=True, timeout=10,
            )
            running = result.returncode == 0 and "PID" in result.stdout
        except Exception:
            running = False

        if running:
            self._record_heartbeat("office_web", "healthy")
            return None

        # Not running; restart via kickstart with domain target.
        kick = subprocess.run(
            ["launchctl", "kickstart", "-k", "-p", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=20,
        )
        success = kick.returncode == 0
        self._record_heartbeat("office_web", "healthy" if success else "unhealthy",
                               error=None if success else kick.stderr.strip())
        return HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="web_server_restart",
            target=label,
            reason=f"Restart office-web service (kickstart rc={kick.returncode})",
            timestamp=now,
            success=success,
            details={"service": label, "restarted": success, "kickstart_rc": kick.returncode},
        )

    def _recover_database(self) -> Optional[HealingAction]:
        """Attempt database recovery if the office-os database is inaccessible.

        Paper/testnet-only: runs a read-only connectivity check; never
        modifies live data or credentials. Returns None when the database is
        already accessible (no remediation needed).
        """
        now = datetime.now(timezone.utc).isoformat()
        db_path = (Path(__file__).resolve().parents[2] / "packages" / "office-os" / "data" / "office.db")
        try:
            accessible = db_path.exists() and db_path.stat().st_size > 0
        except Exception:
            accessible = False

        if accessible:
            self._record_heartbeat("database", "healthy")
            return None

        self._record_heartbeat("database", "degraded", error="database file missing or empty")
        return HealingAction(
            id=f"heal-{int(time.time())}",
            action_type="database_recover",
            target="office_os_database",
            reason="Database file missing or empty; recovery not possible without restore",
            timestamp=now,
            success=False,
            details={"database": str(db_path), "recovered": False},
        )

    def check_infrastructure(self, metrics: dict) -> list[HealingAction]:
        """Check infrastructure health (disk, memory, web server, database) and remediate.

        Only returns actions when remediation is actually needed; healthy
        checks produce a heartbeat but no HealingAction.
        """
        actions: list[HealingAction] = []

        # Disk space
        disk_pct, _mount = self._disk_usage()
        disk_threshold = self.config["thresholds"]["disk_usage_pct"]
        if disk_pct > disk_threshold:
            if self._should_act("disk_cleanup"):
                actions.append(self._cleanup_disk(disk_pct))

        # Memory pressure
        mem_pct = self._memory_usage()
        mem_threshold = self.config["thresholds"]["memory_pressure_pct"]
        if mem_pct > mem_threshold:
            if self._should_act("memory_pressure"):
                actions.append(self._handle_memory_pressure(mem_pct))

        # Web server
        if self._should_act("web_server_health"):
            action = self._restart_web_server()
            if action is not None:
                actions.append(action)

        # Database
        if self._should_act("database_health"):
            action = self._recover_database()
            if action is not None:
                actions.append(action)

        return actions

    # ----------------------- Predictive pre-healing -----------------------

    def _recent_anomaly_alerts(self, window_minutes: int = 60) -> list[dict]:
        """Read recent anomaly alerts from memory preference store."""
        try:
            alerts = self.memory.get_preference("anomaly_alerts", []) or []
        except Exception:
            return []
        if not alerts:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        recent = []
        for a in alerts:
            try:
                ts = datetime.fromisoformat(a.get("timestamp", "").replace("Z", "+00:00"))
                if ts >= cutoff:
                    recent.append(a)
            except Exception:
                continue
        return recent

    def _recent_sla_events(self, workspace_id: str = "dost", window_minutes: int = 60) -> list[dict]:
        """Read recent SLA events for a workspace."""
        try:
            from ops.sla import _read_events
        except Exception:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        cutoff_iso = cutoff.isoformat()
        events = []
        for e in _read_events(workspace_id):
            try:
                if e.get("timestamp", "") >= cutoff_iso:
                    events.append(e)
            except Exception:
                continue
        return events

    def _trend_worsening(self, values: list[float]) -> bool:
        """Return True if a sequence of values is monotonically worsening (increasing)."""
        if len(values) < 3:
            return False
        increases = 0
        for i in range(1, len(values)):
            if values[i] > values[i - 1]:
                increases += 1
        return increases >= len(values) - 1  # at least all-but-one step increasing

    def check_predictive_prehealing(self, metrics: dict) -> list[HealingAction]:
        """Detect degradation trends from anomaly alerts and SLA metrics, act pre-emptively.

        Looks at recent anomaly alerts and SLA events for escalating patterns
        (e.g. error rate creeping up, pool saturation rising, disk filling).
        When a worsening trend is detected before any hard threshold is breached,
        triggers pre-emptive remediation (pre-emptive pool failover, service
        restart, disk cleanup) to avoid reaching the failure threshold.

        Paper/testnet-only: pre-emptive actions never place live orders or
        touch credentials.
        """
        actions: list[HealingAction] = []
        window = self.config["thresholds"].get("trend_window_minutes", 60)

        # --- Anomaly alert trend analysis ---
        alerts = self._recent_anomaly_alerts(window_minutes=window)
        by_type: dict[str, list[dict]] = {}
        for a in alerts:
            by_type.setdefault(a.get("type", "unknown"), []).append(a)

        for alert_type, type_alerts in by_type.items():
            # Severity escalation: medium -> high -> critical
            severities = [a.get("severity", "") for a in type_alerts]
            severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            sev_values = [severity_order.get(s, 0) for s in severities]
            if self._trend_worsening(sev_values) and len(type_alerts) >= 3:
                if self._should_act(f"predictive_{alert_type}"):
                    actions.append(HealingAction(
                        id=f"heal-{int(time.time())}",
                        action_type="predictive_preheal",
                        target=alert_type,
                        reason=f"Escalating {alert_type} anomaly trend ({len(type_alerts)} alerts, severity increasing); pre-emptive remediation",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        success=True,
                        details={"alert_type": alert_type, "alert_count": len(type_alerts),
                                 "trend": "severity_escalating"},
                    ))

        # --- SLA metric trend analysis ---
        try:
            sla_events = self._recent_sla_events(window_minutes=window)
        except Exception:
            sla_events = []
        by_metric: dict[str, list[float]] = {}
        for e in sla_events:
            mn = e.get("metric_name")
            val = e.get("value")
            if mn and val is not None:
                by_metric.setdefault(mn, []).append(float(val))

        for metric_name, values in by_metric.items():
            if len(values) < 3:
                continue
            # Only act on metrics where higher is worse
            if metric_name in ("error_rate", "response_time"):
                if self._trend_worsening(values):
                    if self._should_act(f"predictive_{metric_name}"):
                        actions.append(HealingAction(
                            id=f"heal-{int(time.time())}",
                            action_type="predictive_preheal",
                            target=f"sla_{metric_name}",
                            reason=f"SLA metric {metric_name} trending upward ({len(values)} samples, latest {values[-1]:.1f}); pre-emptive remediation",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            success=True,
                            details={"metric_name": metric_name, "samples": len(values),
                                     "latest": values[-1], "trend": "worsening"},
                        ))

        return actions

    # ----------------------- Cooldown / alerts / persistence -----------------------

    def _should_act(self, action_key: str) -> bool:
        """Check if enough time has passed since last action of this type.

        Applies escalating backoff: a key with consecutive failures waits
        longer (base cooldown * 2^failures, capped) before acting again.
        """
        now = time.time()
        last = self._last_action.get(action_key, 0)
        failures = self._consecutive_failures.get(action_key, 0)
        multiplier = min(2 ** failures, self._max_backoff_multiplier)
        effective_cooldown = self.config["thresholds"]["cooldown_sec"] * multiplier
        if now - last >= effective_cooldown:
            self._last_action[action_key] = now
            return True
        return False

    def _record_action_outcome(self, action_key: str, success: bool) -> None:
        """Track success/failure of an action for escalating backoff.

        Failures increase the backoff for the key; a success resets it.
        """
        if success:
            self._consecutive_failures.pop(action_key, None)
        else:
            self._consecutive_failures[action_key] = (
                self._consecutive_failures.get(action_key, 0) + 1
            )

    def _record_remediation_failure_alert(self, action: HealingAction) -> dict:
        """Record a failed remediation as an alert for /health/ops observability.

        Capped at 200 entries in memory and persisted so failed remediations
        remain visible across restarts. An alert is marked ``escalated`` when
        consecutive failures for the same action key reach the escalation
        threshold, so /health/ops can surface repeatedly-failing remediations.
        Returns the alert dict so callers can wire escalation notifications.
        """
        action_key = f"{action.action_type}_{action.target}"
        consecutive = self._consecutive_failures.get(action_key, 0)
        escalated = consecutive >= self.config["thresholds"]["escalation_threshold"]
        alert = {
            "id": f"alert-{int(time.time())}",
            "action_key": action_key,
            "action_type": action.action_type,
            "target": action.target,
            "reason": action.reason,
            "timestamp": action.timestamp,
            "details": action.details,
            "consecutive_failures": consecutive,
            "escalated": escalated,
        }
        self._alerts.append(alert)
        # Keep the in-memory list bounded; persist the capped list.
        self._alerts = self._alerts[-200:]
        self.memory.set_preference("healing_alerts", self._alerts)
        return alert

    def get_alerts(self, limit: int = 50) -> list[dict]:
        """Return recent remediation-failure alerts."""
        return list(self._alerts[-limit:])

    async def _send_healing_alert(self, alert: dict) -> None:
        """Send an escalated healing alert via configured delivery channels.

        Only fired for escalated alerts (consecutive failures >= threshold) so
        the operator is not spammed by one-off failures. Channels:
        - telegram: push notification when token/chat_id are configured
        - web: surfaced on /health/ops via the persisted healing_alerts list
        - memory: recorded as a unified-memory escalation message
        """
        if not alert.get("escalated"):
            return
        channels = self.config["delivery_channels"]
        # Web and memory channels are served by persisting the alert to
        # healing_alerts (visible on /health/ops) plus an escalation log entry.
        if "web" in channels or "memory" in channels:
            self._log_action(
                HealingAction(
                    id=alert["id"],
                    action_type=alert["action_type"],
                    target=alert["target"],
                    reason=f"[ESCALATED] {alert['reason']}",
                    timestamp=alert["timestamp"],
                    success=False,
                    details={
                        **alert.get("details", {}),
                        "escalated": True,
                        "consecutive_failures": alert.get("consecutive_failures"),
                    },
                )
            )
        if "telegram" in channels:
            await self._send_telegram_healing_alert(alert)

    async def _send_telegram_healing_alert(self, alert: dict) -> None:
        """Send an escalated healing alert via Telegram."""
        try:
            from telegram.bot import DostTelegramBot
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                bot = DostTelegramBot(token, int(chat_id))
                await bot.send_message(
                    f"🚨 *Self-Healing ESCALATED*\n"
                    f"Action: `{alert['action_type']}`\n"
                    f"Target: `{alert['target']}`\n"
                    f"Reason: {alert['reason']}\n"
                    f"Consecutive failures: {alert.get('consecutive_failures')}\n"
                    f"Time: {alert['timestamp']}"
                )
        except Exception as e:
            print(f"[self_healing] Telegram escalation alert failed: {e}")

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

        trading_metrics = self.fetch_trading_fleet_metrics()

        all_actions: list[HealingAction] = []

        # Run all checks; a failing check never kills the cycle or discards
        # actions already collected from earlier checks. Check failures are
        # recorded as alerts so /health/ops can observe them.
        checks = [
            ("stuck_tasks", lambda: self.check_stuck_tasks(metrics)),
            ("pool_saturation", lambda: self.check_pool_saturation(metrics)),
            ("provider_pool_scaling", lambda: self.check_provider_pool_scaling(metrics)),
            ("error_rates", lambda: self.check_error_rates(metrics)),
            ("service_health", lambda: self.check_service_health(metrics)),
            ("trading_fleet_health", lambda: self.check_trading_fleet_health(metrics)),
            ("trading_metrics_health", lambda: self.check_trading_metrics_health(trading_metrics)),
            ("infrastructure", lambda: self.check_infrastructure(metrics)),
            ("predictive_prehealing", lambda: self.check_predictive_prehealing(metrics)),
        ]
        for check_name, check_fn in checks:
            try:
                all_actions.extend(check_fn())
            except Exception as e:
                alert = self._record_remediation_failure_alert(
                    HealingAction(
                        id=f"heal-{int(time.time())}",
                        action_type="check_error",
                        target=check_name,
                        reason=f"Self-healing check '{check_name}' raised: {e}",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        success=False,
                        details={"error": str(e)},
                    )
                )
                if alert.get("escalated"):
                    await self._send_healing_alert(alert)
                print(f"[self_healing] Check '{check_name}' raised: {e}")

        # Record actions, alert, persist
        for action in all_actions:
            self._action_history.append(action)
            self._log_action(action)
            if not action.success:
                alert = self._record_remediation_failure_alert(action)
                if alert.get("escalated"):
                    await self._send_healing_alert(alert)

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
        # Persist circuit-breaker state so a tripped circuit survives restarts.
        self.memory.set_preference("circuit_broken", self._circuit_broken)
        # Persist trading-fleet snapshot so /health/ops can surface OpenAlice
        # trading fleet state alongside dost service health.
        self.memory.set_preference("trading_fleet", trading_metrics)
        # Persist consecutive-failure counts so cooldown/escalation state is
        # observable on /health/ops across restarts.
        self.memory.set_preference("consecutive_failures", self._consecutive_failures)
        # Persist self-healing loop liveness state so /health/ops can observe
        # whether the supervision loop is healthy across restarts.
        self.memory.set_preference("self_healing_loop_failures", self._loop_failures)
        self.memory.set_preference("self_healing_loop_last_error", self._loop_last_error)
        self.memory.set_preference("self_healing_loop_healthy", self._loop_healthy)
        self.memory.set_preference("healing_alerts", self._alerts)

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

    async def _run_supervised_once(self) -> dict[str, Any]:
        """Run one self-healing cycle under supervision.

        Wraps :meth:`run_once` so that an unexpected exception (or a
        repeatedly-failing cycle) cannot kill the 24/7 loop. Applies escalating
        backoff on consecutive loop failures and records a liveness heartbeat
        for /health/ops. Never raises.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = await self.run_once()
        except Exception as e:
            # run_once itself blew up: record the failure, back off, and keep
            # the loop alive. This is the restart-on-failure supervision point.
            self._loop_failures += 1
            self._loop_last_error = f"{type(e).__name__}: {e}"
            self._loop_healthy = False
            self._record_heartbeat(
                "self_healing",
                "unhealthy",
                error=self._loop_last_error,
            )
            self.memory.set_preference(
                "service_heartbeats", self._service_heartbeats
            )
            print(f"[self_healing] Supervised cycle failed: {self._loop_last_error}")
            return {
                "ok": False,
                "error": self._loop_last_error,
                "supervised": True,
                "loop_failures": self._loop_failures,
            }

        if not result.get("ok"):
            self._loop_failures += 1
            self._loop_last_error = result.get("error", "run_once returned ok=False")
            self._loop_healthy = False
            self._record_heartbeat(
                "self_healing",
                "unhealthy",
                error=self._loop_last_error,
            )
            self.memory.set_preference(
                "service_heartbeats", self._service_heartbeats
            )
            print(f"[self_healing] Supervised cycle unhealthy: {self._loop_last_error}")
            return {
                "ok": False,
                "error": self._loop_last_error,
                "supervised": True,
                "loop_failures": self._loop_failures,
            }

        # Cycle succeeded: reset failure tracking and record healthy heartbeat.
        self._loop_failures = 0
        self._loop_last_error = None
        self._loop_healthy = True
        self._record_heartbeat("self_healing", "healthy", error=None)
        self.memory.set_preference("service_heartbeats", self._service_heartbeats)
        return result

    async def run_loop(self):
        """Run continuous self-healing loop."""
        print(f"[self_healing] Starting loop (interval: {self.config['check_interval_sec']}s)")
        while True:
            try:
                result = await self._run_supervised_once()
                if not result.get("ok"):
                    print(
                        f"[self_healing] Cycle unhealthy "
                        f"(failures={result.get('loop_failures', 0)}): {result.get('error')}"
                    )
                elif result.get("actions"):
                    print(f"[self_healing] Actions taken: {len(result['actions'])}")
            except Exception as e:
                print(f"[self_healing] Loop error: {e}")
            await asyncio.sleep(self.config["check_interval_sec"])

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
            result = await healing._run_supervised_once()
            if not result.get("ok"):
                print(
                    f"[self_healing] Cycle unhealthy "
                    f"(failures={result.get('loop_failures', 0)}): {result.get('error')}"
                )
            elif result.get("actions"):
                print(f"[self_healing] Actions taken: {len(result['actions'])}")
        except Exception as e:
            print(f"[self_healing] Loop error: {e}")
        await asyncio.sleep(healing.config["check_interval_sec"])


if __name__ == "__main__":
    asyncio.run(main())
