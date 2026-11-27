"""Tests for dost ops autonomy modules (anomaly watch, self-healing,
opportunity scanner, proactive scheduler, proactive agent).

Covers the config-merge fix (partial orchestrator config keeps default
tables) and graceful degradation when external dependencies are unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from ops.anomaly_watch import AnomalyWatch, ANOMALY_CONFIG
from ops.opportunity_scanner import OpportunityScanner, SCANNER_CONFIG
from ops.proactive_agent import ProactiveAgent
from ops.proactive_scheduler import ProactiveScheduler, SCHEDULER_CONFIG
from ops.self_healing import FleetSelfHealing, HEALING_CONFIG


class FakeMemory:
    """In-memory stand-in for the unified memory layer."""

    def __init__(self) -> None:
        self.prefs: dict = {}
        self.messages: list = []

    def get_preference(self, key: str, default=None):
        return self.prefs.get(key, default)

    def set_preference(self, key: str, value) -> None:
        self.prefs[key] = value

    def add_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))


def test_anomaly_watch_partial_config_keeps_default_thresholds(monkeypatch):
    """Orchestrator passes partial config; default thresholds must survive."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.anomaly_watch.get_unified_memory", lambda: fake)
    watch = AnomalyWatch({"enabled": True, "check_interval_sec": 60})
    assert watch.config["thresholds"] == ANOMALY_CONFIG["thresholds"]
    assert watch.config["enabled"] is True
    assert watch.config["check_interval_sec"] == 60


def test_self_healing_partial_config_keeps_default_thresholds(monkeypatch):
    """Orchestrator passes partial config; default thresholds must survive."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing({"enabled": True, "check_interval_sec": 60})
    assert heal.config["thresholds"] == HEALING_CONFIG["thresholds"]
    assert heal.config["enabled"] is True


def test_anomaly_watch_run_once_degrades_when_metrics_unavailable(monkeypatch):
    """Unreachable metrics endpoint degrades to ok=False, no crash."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.anomaly_watch.get_unified_memory", lambda: fake)

    watch = AnomalyWatch()
    monkeypatch.setattr(watch, "fetch_metrics", lambda: {})

    result = asyncio.run(watch.run_once())
    assert result["ok"] is False
    assert result["error"] == "Failed to fetch metrics"


def test_anomaly_watch_checks_run_against_live_metrics(monkeypatch):
    """All checks run against fetched metrics; elevated error rate alerts."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.anomaly_watch.get_unified_memory", lambda: fake)

    watch = AnomalyWatch()
    metrics = {
        "jev": {"error_rate": 99.0, "pending_tasks": 0},
        "provider_pools": {},
    }
    monkeypatch.setattr(watch, "fetch_metrics", lambda: metrics)

    import asyncio

    result = asyncio.run(watch.run_once())
    assert result["ok"] is True
    checks = {c["check"]: c["alerted"] for c in result["checks"]}
    assert checks["error_rate"] is True
    assert result["alerts"][0]["type"] == "error_rate"


def test_self_healing_run_once_degrades_when_metrics_unavailable(monkeypatch):
    """Unreachable metrics endpoint degrades to ok=False, no crash."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    monkeypatch.setattr(heal, "fetch_fleet_metrics", lambda: {})

    result = asyncio.run(heal.run_once())
    assert result["ok"] is False
    assert result["error"] == "Failed to fetch metrics"


def test_self_healing_pool_saturation_triggers_failover(monkeypatch, tmp_path):
    """Saturated pool produces a pool_failover healing action.

    Hermetic: run_once() runs every check, so the real hive dir and launchctl
    are stubbed out; only pool saturation failover is exercised here.
    """
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    monkeypatch.setattr(
        "ops.self_healing.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="PID 123", stderr=""),
    )

    heal = FleetSelfHealing()
    metrics = {
        "provider_pools": {
            "nvidia_key1": {"available": 1, "total": 10},  # 90% saturated > 85%
        }
    }
    monkeypatch.setattr(heal, "fetch_fleet_metrics", lambda: metrics)

    import asyncio

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True
    assert len(result["actions"]) == 1
    assert result["actions"][0]["type"] == "pool_failover"
    assert result["actions"][0]["target"] == "nvidia_key1"


def test_opportunity_scanner_partial_config_keeps_default_screens(monkeypatch):
    """Partial orchestrator config keeps default screens and overrides scalars."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.opportunity_scanner.get_unified_memory", lambda: fake)

    scanner = OpportunityScanner({"enabled": True, "schedule_interval_sec": 120})
    assert scanner.config["enabled"] is True
    assert scanner.config["schedule_interval_sec"] == 120
    assert scanner.config["screens"] == SCANNER_CONFIG["screens"]


def test_opportunity_scanner_run_once_dispatches_all_screens(monkeypatch):
    """run_once dispatches every enabled screen via the fleet and records delivery."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.opportunity_scanner.get_unified_memory", lambda: fake)

    scanner = OpportunityScanner({"delivery_channels": ["web"]})

    prompts = []

    def fake_dispatch(prompt, agent_id="research"):
        prompts.append(prompt)
        return {"ok": True, "task_id": "task-1", "agent_id": "research"}

    monkeypatch.setattr("ops.opportunity_scanner.dispatch_prompt_to_fleet", fake_dispatch)

    result = asyncio.run(scanner.run_once())

    assert result["ok"] is True
    assert result["delivered"] == {"web": True}
    screens = [r["screen"] for r in result["results"]]
    assert screens == [
        "value",
        "quality",
        "technical_breakout",
        "funding_rate_arb",
        "governance",
        "earnings_catalyst",
    ]
    assert len(prompts) == 6
    assert all(r["status"] == "dispatched" for r in result["results"])
    assert fake.prefs["last_opportunity_scan"]["results"] == result["results"]


def test_opportunity_scanner_synthesize_opportunities():
    """synthesize_opportunities renders dispatched/failed lines and a total."""
    scanner = OpportunityScanner()
    results = [
        {"screen": "value", "status": "dispatched", "task_id": "abc-123"},
        {"screen": "governance", "status": "failed", "error": "boom"},
    ]
    summary = scanner.synthesize_opportunities(results)
    assert "✅ *value*: Dispatched (task: abc-123)" in summary
    assert "❌ *governance*: Failed - boom" in summary
    assert "_Total screens: 2_" in summary


def test_opportunity_scanner_disabled(monkeypatch):
    """Disabled scanner returns ok without dispatching anything."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.opportunity_scanner.get_unified_memory", lambda: fake)

    scanner = OpportunityScanner({"enabled": False})

    def should_not_dispatch(*args, **kwargs):
        raise AssertionError("dispatch_prompt_to_fleet must not be called")

    monkeypatch.setattr("ops.opportunity_scanner.dispatch_prompt_to_fleet", should_not_dispatch)

    result = asyncio.run(scanner.run_once())
    assert result == {"ok": True, "results": []}


def test_proactive_scheduler_partial_config_keeps_default_jobs():
    """Partial config must not drop the default job table."""
    sched = ProactiveScheduler({"enabled": True})
    assert sched.config["enabled"] is True
    assert sched.config["jobs"] == SCHEDULER_CONFIG["jobs"]


def test_proactive_scheduler_adds_enabled_jobs_and_skips_disabled(monkeypatch):
    """start() adds jobs from config; disabled jobs are skipped."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.proactive_scheduler.get_unified_memory", lambda: fake)
    monkeypatch.setattr(
        ProactiveScheduler,
        "_load_config_from_office_json",
        lambda self: {
            "enabled": True,
            "jobs": {
                "morning_briefing": {
                    "enabled": True,
                    "trigger": "cron",
                    "hour": 6,
                    "minute": 0,
                    "timezone": "UTC",
                },
                "anomaly_watch": {"enabled": True, "trigger": "interval", "seconds": 60},
                "opportunity_scanner": {"enabled": False},
            },
        },
    )

    sched = ProactiveScheduler()
    assert sched.start() is True
    try:
        jobs = {job.id for job in sched.scheduler.get_jobs()}
        assert jobs == {"morning_briefing", "anomaly_watch"}
    finally:
        sched.stop()


def test_proactive_scheduler_status_before_start():
    """get_job_status reports not-running with no jobs before start()."""
    sched = ProactiveScheduler()
    status = sched.get_job_status()
    assert status == {"running": False, "jobs": {}}


async def _block_forever():
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_proactive_agent_starts_all_services_and_stop_cancels_tasks(monkeypatch):
    """Agent constructs all four services; start() launches loops, stop() cancels tasks."""
    fake = FakeMemory()
    for mod in (
        "ops.proactive_scheduler",
        "ops.anomaly_watch",
        "ops.opportunity_scanner",
        "ops.self_healing",
    ):
        monkeypatch.setattr(f"{mod}.get_unified_memory", lambda: fake)

    monkeypatch.setattr(ProactiveScheduler, "start", lambda self: True)
    monkeypatch.setattr(ProactiveScheduler, "stop", lambda self: None)
    for name in ("_run_anomaly_watch", "_run_opportunity_scanner", "_run_self_healing"):
        monkeypatch.setattr(ProactiveAgent, name, lambda self: _block_forever())

    config = {
        "scheduler": {"enabled": True, "jobs": {}},
        "morning_briefing": {"enabled": False},
    }
    agent = ProactiveAgent(config)
    assert agent.scheduler is not None
    assert agent.anomaly_watch is not None
    assert agent.opportunity_scanner is not None
    assert agent.self_healing is not None
    assert agent.running is False

    start_task = asyncio.create_task(agent.start())
    try:
        await asyncio.sleep(0.05)
        assert agent.running is True
        assert len(agent.tasks) == 3
    finally:
        agent.stop()
        await start_task
        assert all(task.cancelled() for task in agent.tasks)
        assert agent.running is False


# ----------------------- Remediation path tests -----------------------

def _fake_subprocess(monkeypatch, restart_rc=0, kickstart_rc=0, list_running=False):
    """Stub launchctl: 'list' reports running status; restart/kickstart return given rc."""

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["launchctl", "list"]:
            return SimpleNamespace(
                returncode=0 if list_running else 1,
                stdout="PID 123" if list_running else "",
                stderr="",
            )
        if cmd[:2] == ["launchctl", "restart"]:
            return SimpleNamespace(returncode=restart_rc, stdout="", stderr="")
        if cmd[:2] == ["launchctl", "kickstart"]:
            return SimpleNamespace(returncode=kickstart_rc, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("ops.self_healing.subprocess.run", fake_run)


def _fake_dispatch(monkeypatch):
    calls = []

    def fake_dispatch(prompt, agent_id="strategy-advisor", priority="normal", dry_run=False):
        calls.append((prompt, agent_id, priority, dry_run))
        return {"ok": True, "task_id": "new-task"}

    monkeypatch.setattr("ops.self_healing.dispatch_prompt_to_fleet", fake_dispatch)
    return calls


def _write_hive_task(tmp_path, task_id, status, **overrides):
    task = {
        "id": task_id,
        "title": f"Task {task_id}",
        "description": "do the thing",
        "status": status,
        "agent_id": "strategy-advisor",
        "priority": "normal",
        "metadata": {},
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(),
    }
    task.update(overrides)
    (tmp_path / f"{task_id}.json").write_text(json.dumps(task, indent=2))
    return task


def test_self_healing_restart_service_ok(monkeypatch):
    """launchctl restart succeeds -> service_restart action, healthy heartbeat."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    _fake_subprocess(monkeypatch, restart_rc=0, list_running=True)

    action = heal._restart_service("com.aryan.dost-proactive-agent")

    assert action.action_type == "service_restart"
    assert action.target == "com.aryan.dost-proactive-agent"
    assert action.success is True
    assert action.details["restarted"] is True
    assert heal._service_heartbeats["com.aryan.dost-proactive-agent"]["status"] == "healthy"


def test_self_healing_restart_service_kickstart_fallback(monkeypatch):
    """restart fails, kickstart succeeds -> still a successful service_restart."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=0)

    action = heal._restart_service("dev.krisharyanagarwal.dost-telegram-bot")

    assert action.success is True
    assert action.details["restarted"] is False
    assert action.details["kickstarted"] is True


def test_self_healing_restart_service_total_failure(monkeypatch):
    """restart and kickstart both fail -> unsuccessful service_restart, unhealthy heartbeat."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=1)

    action = heal._restart_service("com.aryan.dost-monitor")

    assert action.success is False
    assert action.details["restarted"] is False
    assert action.details["kickstarted"] is False
    assert heal._service_heartbeats["com.aryan.dost-monitor"]["status"] == "unhealthy"


def test_self_healing_clear_task_backlog_redispatches_stuck_task(monkeypatch, tmp_path):
    """in_progress task with no update beyond task_stuck_minutes is re-dispatched."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing()
    dispatch_calls = _fake_dispatch(monkeypatch)

    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    _write_hive_task(tmp_path, "task-stuck-1", "in_progress", updated_at=old)

    actions = heal._clear_task_backlog({})

    assert len(actions) == 1
    assert actions[0].action_type == "stuck_task_redispatch"
    assert actions[0].target == "task-stuck-1"
    assert actions[0].success is True
    assert actions[0].details["old_status"] == "in_progress"
    assert dispatch_calls == [("do the thing", "strategy-advisor", "normal", False)]

    updated = json.loads((tmp_path / "task-stuck-1.json").read_text())
    assert updated["status"] == "redispatched"
    assert updated["metadata"]["redispatch_count"] == 1
    assert "last_redispatch_at" in updated["metadata"]


def test_self_healing_clear_task_backlog_redispatches_failed_under_retries(
    monkeypatch, tmp_path
):
    """failed task below max_retries is re-dispatched and counter incremented."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing()
    _fake_dispatch(monkeypatch)

    _write_hive_task(
        tmp_path, "task-failed-1", "failed", updated_at="", metadata={"redispatch_count": 0}
    )

    actions = heal._clear_task_backlog({})

    assert len(actions) == 1
    assert actions[0].details["retry_count"] == 1
    assert actions[0].details["max_retries"] == 3

    updated = json.loads((tmp_path / "task-failed-1.json").read_text())
    assert updated["status"] == "redispatched"
    assert updated["metadata"]["redispatch_count"] == 1


def test_self_healing_clear_task_backlog_skips_max_retries(monkeypatch, tmp_path):
    """failed task at max_retries is not re-dispatched."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing()
    dispatch_calls = _fake_dispatch(monkeypatch)

    _write_hive_task(
        tmp_path, "task-failed-2", "failed", updated_at="", metadata={"redispatch_count": 3}
    )

    actions = heal._clear_task_backlog({})
    assert actions == []
    assert dispatch_calls == []


def test_self_healing_clear_task_backlog_skips_ineligible(monkeypatch, tmp_path):
    """recently updated, done, and idless tasks are skipped."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing()
    dispatch_calls = _fake_dispatch(monkeypatch)

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _write_hive_task(tmp_path, "task-recent", "in_progress", updated_at=recent)
    _write_hive_task(tmp_path, "task-done", "done", updated_at=recent)
    (tmp_path / "task-noid.json").write_text(
        json.dumps({"status": "in_progress", "updated_at": recent})
    )

    actions = heal._clear_task_backlog({})
    assert actions == []
    assert dispatch_calls == []


def test_self_healing_pool_failover_then_recovery(monkeypatch):
    """saturated pool fails over; once below recovery threshold it recovers."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()

    saturated = {"provider_pools": {"nvidia_key1": {"available": 1, "total": 10}}}  # 90%
    actions = heal.check_pool_saturation(saturated)
    assert len(actions) == 1
    assert actions[0].action_type == "pool_failover"
    assert actions[0].target == "nvidia_key1"
    assert fake.prefs["failed_over_pools"] == ["nvidia_key1"]

    # Already failed over: re-checking while still saturated must not fail over again.
    assert heal.check_pool_saturation(saturated) == []

    recovered = {"provider_pools": {"nvidia_key1": {"available": 9, "total": 10}}}  # 10%
    actions = heal.check_pool_saturation(recovered)
    assert len(actions) == 1
    assert actions[0].action_type == "pool_recover"
    assert actions[0].target == "nvidia_key1"
    assert fake.prefs["failed_over_pools"] == []


def test_self_healing_circuit_break_then_recover(monkeypatch):
    """error rate above threshold trips the circuit; below half threshold resets it."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()

    actions = heal.check_error_rates({"jev": {"error_rate": 99.0}})  # > 10%
    assert len(actions) == 1
    assert actions[0].action_type == "circuit_break"
    assert actions[0].target == "fleet_dispatch"
    assert heal._circuit_broken is True

    # Still elevated but below threshold: no new action, circuit stays open.
    assert heal.check_error_rates({"jev": {"error_rate": 9.0}}) == []
    assert heal._circuit_broken is True

    actions = heal.check_error_rates({"jev": {"error_rate": 1.0}})  # < 5%
    assert len(actions) == 1
    assert actions[0].action_type == "circuit_recover"
    assert heal._circuit_broken is False


def test_self_healing_cooldown_blocks_repeat_action(monkeypatch):
    """same action key is suppressed until cooldown elapses; keys are independent."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    config = {
        "enabled": True,
        "thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 60},
    }
    heal = FleetSelfHealing(config)

    assert heal._should_act("pool_failover_x") is True
    assert heal._should_act("pool_failover_x") is False
    assert heal._should_act("other_key") is True


def test_self_healing_run_once_end_to_end(monkeypatch, tmp_path):
    """run_once fails over saturated pool, breaks circuit, restarts down services."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)  # no real hive tasks

    heal = FleetSelfHealing({"delivery_channels": ["web"]})
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {
            "provider_pools": {"nvidia_key1": {"available": 1, "total": 10}},  # 90%
            "jev": {"error_rate": 99.0},
        },
    )
    _fake_subprocess(monkeypatch, restart_rc=0, list_running=False)  # all services down

    result = asyncio.run(heal.run_once())

    assert result["ok"] is True
    types = {a["type"] for a in result["actions"]}
    assert types == {"pool_failover", "circuit_break", "service_restart"}
    assert len(result["actions"]) == 6  # 1 pool + 1 circuit + 4 service restarts
    assert all(a["success"] for a in result["actions"])

    # Persisted observability state for the /health/ops dashboard.
    assert fake.prefs["failed_over_pools"] == ["nvidia_key1"]
    assert (
        fake.prefs["service_heartbeats"]["com.aryan.dost-proactive-agent"]["status"]
        == "healthy"
    )
    assert len(fake.prefs["last_healing_actions"]) == 6


def test_self_healing_run_once_disabled(monkeypatch):
    """disabled self-healing short-circuits: no metrics fetch, no actions."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing({"enabled": False})
    fetched = []
    monkeypatch.setattr(heal, "fetch_fleet_metrics", lambda: fetched.append(True) or {})

    result = asyncio.run(heal.run_once())
    assert result == {"ok": True, "actions": []}
    assert fetched == []


# ----------------------- Watchdog tests -----------------------

def test_watchdog_restarts_agent_when_down(monkeypatch, tmp_path):
    """run_once kickstarts the proactive agent when pgrep finds no process."""
    import ops.watchdog as watchdog

    watchdog.LOG_PATH = tmp_path / "dost-watchdog.log"

    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(list(cmd))
        if cmd[:2] == ["pgrep", "-f"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")  # not running
        if cmd[:2] == ["launchctl", "kickstart"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    watchdog.run_once()

    assert any(c[:2] == ["launchctl", "kickstart"] for c in cmds)
    assert any(len(c) > 3 and c[3] == "com.aryan.dost-proactive-agent" for c in cmds)


def test_watchdog_no_restart_when_agent_running(monkeypatch, tmp_path):
    """run_once does not kickstart when the proactive agent process is alive."""
    import ops.watchdog as watchdog

    watchdog.LOG_PATH = tmp_path / "dost-watchdog.log"

    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(list(cmd))
        if cmd[:2] == ["pgrep", "-f"]:
            return SimpleNamespace(returncode=0, stdout="3184", stderr="")  # running
        if cmd[:2] == ["launchctl", "kickstart"]:
            raise AssertionError("kickstart must not be called when agent is running")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    watchdog.run_once()

    assert not any(c[:2] == ["launchctl", "kickstart"] for c in cmds)
