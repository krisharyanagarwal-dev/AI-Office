"""Tests for dost ops autonomy modules (anomaly watch, self-healing,
opportunity scanner, proactive scheduler, proactive agent).

Covers the config-merge fix (partial orchestrator config keeps default
tables) and graceful degradation when external dependencies are unavailable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util as _importlib_util
import json
import os
from types import SimpleNamespace

import pytest

# Load the chaos fault-injection library by file path: a plain
# `from tests.test_chaos import` would bind packages/office-os's shadowing
# `tests` package instead of dost/tests/test_chaos.py.
_chaos_path = os.path.join(os.path.dirname(__file__), "test_chaos.py")
_chaos_spec = _importlib_util.spec_from_file_location("dost_ops_autonomy_test_chaos", _chaos_path)
_chaos_mod = _importlib_util.module_from_spec(_chaos_spec)
_chaos_spec.loader.exec_module(_chaos_mod)  # type: ignore[union-attr]

inject_provider_failure = _chaos_mod.inject_provider_failure
is_provider_failed = _chaos_mod.is_provider_failed
clear_provider_failure = _chaos_mod.clear_provider_failure
reset_failures = _chaos_mod.reset_failures

from ops.anomaly_watch import AnomalyWatch, ANOMALY_CONFIG
from ops.opportunity_scanner import OpportunityScanner, SCANNER_CONFIG
from ops.proactive_agent import ProactiveAgent
from ops.proactive_scheduler import ProactiveScheduler, SCHEDULER_CONFIG
from ops.self_healing import (
    FleetSelfHealing,
    HealingAction,
    HEALING_CONFIG,
    SERVICE_LABELS,
)


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
    # Infrastructure is healthy in this scenario: database remediation is
    # exercised by its own tests (the real office.db does not exist here).
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

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

    def fake_dispatch(prompt, agent_id="research", priority="normal", dry_run=False, extra_metadata=None):
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

    def fake_dispatch(prompt, agent_id="strategy-advisor", priority="normal", dry_run=False, extra_metadata=None):
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
    """kickstart succeeds -> service_restart action, healthy heartbeat."""
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


def test_self_healing_restart_service_kickstart_succeeds(monkeypatch):
    """kickstart succeeds -> successful service_restart with restarted and kickstarted set."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=0)

    action = heal._restart_service("dev.krisharyanagarwal.dost-telegram-bot")

    assert action.success is True
    assert action.details["restarted"] is True
    assert action.details["kickstarted"] is True


def test_self_healing_restart_service_total_failure(monkeypatch):
    """kickstart fails -> unsuccessful service_restart, unhealthy heartbeat."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

    heal = FleetSelfHealing()
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=1)

    action = heal._restart_service("com.aryan.dost-monitor")

    assert action.success is False
    assert action.details["restarted"] is False
    assert action.details["kickstarted"] is False
    assert heal._service_heartbeats["com.aryan.dost-monitor"]["status"] == "unhealthy"


# ----------------------- Trading fleet tests -----------------------

def test_fetch_trading_fleet_metrics_parses_text(monkeypatch):
    """Prometheus text from :9109/metrics parses into {metric: {label_key: value}}."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing()

    text = (
        "# HELP fleet_health_ok 1 if every verified check passed.\n"
        "# TYPE fleet_health_ok gauge\n"
        "fleet_health_ok 1\n"
        "fleet_agents_alive 40\n"
        "fleet_agents_expected 42\n"
        "fleet_agents_dead 2\n"
        "fleet_checks_failing 3\n"
        'fleet_check_ok{check="hive"} 1\n'
        'fleet_check_level{check="tasks"} 2\n'
        "# TYPE fleet_checks_failing gauge\n"
        "garbage line without value\n"
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=text, stderr="")

    monkeypatch.setattr("ops.self_healing.subprocess.run", fake_run)

    metrics = heal.fetch_trading_fleet_metrics()
    assert metrics["fleet_health_ok"][""] == 1.0
    assert metrics["fleet_agents_alive"][""] == 40.0
    assert metrics["fleet_agents_expected"][""] == 42.0
    assert metrics["fleet_agents_dead"][""] == 2.0
    assert metrics["fleet_checks_failing"][""] == 3.0
    assert metrics["fleet_check_ok"]['{check="hive"}'] == 1.0
    assert metrics["fleet_check_level"]['{check="tasks"}'] == 2.0
    # Malformed lines are skipped, not fatal.


def test_fetch_trading_fleet_metrics_unreachable_returns_empty(monkeypatch, capsys):
    """Exporter down degrades to {} instead of crashing the cycle."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing()

    def fake_run(cmd, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("ops.self_healing.subprocess.run", fake_run)
    assert heal.fetch_trading_fleet_metrics() == {}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[self_healing] Failed to fetch trading fleet metrics" in captured.err


def _trading_heal(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )
    return heal, fake


def test_check_trading_fleet_health_restarts_down_services(monkeypatch):
    """Down trading_bot and fleet_metrics launchd services are restarted."""
    heal, _ = _trading_heal(monkeypatch)
    _fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    actions = heal.check_trading_fleet_health({})

    assert len(actions) == 2
    assert all(a.action_type == "service_restart" for a in actions)
    assert {a.target for a in actions} == {"com.aryan.trading-bot", "com.aryan.fleet-metrics"}
    assert all(a.success for a in actions)
    assert "Trading fleet service trading_bot not running; restarting" in actions[0].reason
    assert heal._service_heartbeats["com.aryan.trading-bot"]["status"] == "healthy"
    assert heal._service_heartbeats["com.aryan.fleet-metrics"]["status"] == "healthy"


def test_check_trading_fleet_health_skips_running_services(monkeypatch):
    """Running trading fleet services produce no actions."""
    heal, _ = _trading_heal(monkeypatch)
    _fake_subprocess(monkeypatch, list_running=True, kickstart_rc=1)

    actions = heal.check_trading_fleet_health({})

    assert actions == []


def test_check_trading_metrics_health_degraded_restarts_trading_bot(monkeypatch):
    """fleet_health_ok=0 or failing checks restart the trading bot once per cooldown."""
    heal, _ = _trading_heal(monkeypatch)
    _fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    trading_metrics = {
        "fleet_health_ok": {"": 0.0},
        "fleet_checks_failing": {"": 2.0},
    }
    actions = heal.check_trading_metrics_health(trading_metrics)

    assert len(actions) == 1
    assert actions[0].action_type == "service_restart"
    assert actions[0].target == "com.aryan.trading-bot"
    assert actions[0].success is True
    assert "fleet_health_ok=0" in actions[0].reason
    assert "fleet_checks_failing=2" in actions[0].reason


def test_check_trading_metrics_health_agents_below_expected_restarts(monkeypatch):
    """fewer agents alive than expected restarts the trading bot."""
    heal, _ = _trading_heal(monkeypatch)
    _fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    trading_metrics = {
        "fleet_health_ok": {"": 1.0},
        "fleet_checks_failing": {"": 0.0},
        "fleet_agents_alive": {"": 40.0},
        "fleet_agents_expected": {"": 42.0},
    }
    actions = heal.check_trading_metrics_health(trading_metrics)

    assert len(actions) == 1
    assert actions[0].target == "com.aryan.trading-bot"
    assert "agents 40/42 alive" in actions[0].reason


def test_check_trading_metrics_health_healthy_no_action(monkeypatch):
    """Healthy fleet metrics record a heartbeat but no remediation."""
    heal, _ = _trading_heal(monkeypatch)
    _fake_subprocess(monkeypatch, list_running=False, kickstart_rc=1)

    trading_metrics = {
        "fleet_health_ok": {"": 1.0},
        "fleet_checks_failing": {"": 0.0},
        "fleet_agents_alive": {"": 42.0},
        "fleet_agents_expected": {"": 42.0},
    }
    actions = heal.check_trading_metrics_health(trading_metrics)

    assert actions == []
    assert heal._service_heartbeats["com.aryan.trading-bot"]["status"] == "healthy"


def test_check_trading_metrics_health_empty_metrics_no_action(monkeypatch):
    """Unreachable exporter yields no actions from metrics health check."""
    heal, _ = _trading_heal(monkeypatch)
    assert heal.check_trading_metrics_health({}) == []


def test_run_once_restarts_trading_bot_on_degraded_fleet_metrics(monkeypatch, tmp_path):
    """run_once wires trading fleet metrics degradation into trading bot restart."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)  # no real hive tasks

    heal = FleetSelfHealing(
        {
            "thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0},
            "delivery_channels": ["web"],
        }
    )
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}},
    )
    monkeypatch.setattr(
        heal,
        "fetch_trading_fleet_metrics",
        lambda: {
            "fleet_health_ok": {"": 0.0},
            "fleet_checks_failing": {"": 1.0},
        },
    )
    # All 6 services (4 dost + 2 trading) are down; kickstart succeeds.
    _fake_subprocess(monkeypatch, restart_rc=0, list_running=False, kickstart_rc=0)
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())

    assert result["ok"] is True
    types = {a["type"] for a in result["actions"]}
    assert types == {"service_restart"}
    # 4 dost + 2 trading service restarts + 1 trading-bot metrics restart.
    assert len(result["actions"]) == 7
    assert all(a["success"] for a in result["actions"])
    trading = [a for a in result["actions"] if a["target"] == "com.aryan.trading-bot"]
    # One restart from the down service, one from degraded fleet metrics.
    assert len(trading) == 2
    assert any("degraded" in a["reason"] for a in trading)
    assert fake.prefs["service_heartbeats"]["com.aryan.trading-bot"]["status"] == "healthy"


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


def test_self_healing_never_redispatches_tier_c_agent(monkeypatch, tmp_path):
    """A stuck task for a Tier C (human-only) agent is left alone, not re-run."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    monkeypatch.setattr("ops.self_healing.tier_c_agents", lambda: {"risk-manager"})

    heal = FleetSelfHealing()
    dispatch_calls = _fake_dispatch(monkeypatch)

    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    _write_hive_task(tmp_path, "task-tier-c-1", "in_progress", updated_at=old, agent_id="risk-manager")

    actions = heal._clear_task_backlog({})

    assert actions == []
    assert dispatch_calls == []
    assert json.loads((tmp_path / "task-tier-c-1.json").read_text())["status"] == "in_progress"


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


def test_provider_pool_scales_down_when_saturating(monkeypatch):
    """Boolean available=False (live /metrics shape) at 100% saturation scales a pool down."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )

    metrics = {"provider_pools": {"nvidia_key1": {"available": False}}}
    actions = heal.check_provider_pool_scaling(metrics)
    assert len(actions) == 1
    assert actions[0].action_type == "pool_scale_down"
    assert actions[0].target == "nvidia_key1"
    assert heal._pool_scale_factors["nvidia_key1"] == 0.5
    assert fake.prefs["pool_scale_factors"]["nvidia_key1"] == 0.5


@pytest.mark.parametrize("stored_factors", ["not-a-dict", ["mlx_local"], None])
def test_self_healing_ignores_non_mapping_persisted_pool_factors(stored_factors):
    fake = FakeMemory()
    fake.prefs["pool_scale_factors"] = stored_factors

    heal = FleetSelfHealing(memory=fake)

    assert heal._pool_scale_factors == {}


def test_self_healing_filters_invalid_persisted_pool_factors():
    fake = FakeMemory()
    fake.prefs["pool_scale_factors"] = {
        "valid": 0.5,
        "integer": 1,
        "string": "0.25",
        "boolean": True,
        "nan": float("nan"),
        "infinite": float("inf"),
        "": 0.75,
        7: 0.25,
    }

    heal = FleetSelfHealing(memory=fake)

    assert heal._pool_scale_factors == {"valid": 0.5, "integer": 1.0}


def test_provider_pool_scales_down_to_min_scale_then_stops(monkeypatch):
    """Repeated scale-down approaches but never goes below pool_min_scale."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )

    metrics = {"provider_pools": {"nvidia_key1": {"available": False}}}
    for _ in range(5):
        heal.check_provider_pool_scaling(metrics)
    assert heal._pool_scale_factors["nvidia_key1"] == 0.25  # clamped at min_scale


def test_provider_pool_scales_up_when_recovered(monkeypatch):
    """Boolean available=True (live /metrics shape) at 0% saturation scales a pool back up."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )
    heal._pool_scale_factors["nvidia_key1"] = 0.5  # previously scaled down

    metrics = {"provider_pools": {"nvidia_key1": {"available": True}}}
    actions = heal.check_provider_pool_scaling(metrics)
    assert len(actions) == 1
    assert actions[0].action_type == "pool_scale_up"
    assert heal._pool_scale_factors["nvidia_key1"] == 1.0


def test_provider_pool_skipped_when_failed_over(monkeypatch):
    """A failed-over pool is not auto-scaled; failover owns its routing."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )
    heal._failed_over_pools.add("nvidia_key1")

    metrics = {"provider_pools": {"nvidia_key1": {"available": False}}}  # 100% saturated
    actions = heal.check_provider_pool_scaling(metrics)
    assert actions == []
    assert heal._pool_scale_factors.get("nvidia_key1", 1.0) == 1.0  # unchanged


def test_provider_pool_no_action_when_healthy_saturation(monkeypatch):
    """Pool below scale-down threshold and already at full scale: no action."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )

    metrics = {"provider_pools": {"nvidia_key1": {"available": True}}}  # 0% saturation
    actions = heal.check_provider_pool_scaling(metrics)
    assert actions == []
    assert heal._pool_scale_factors.get("nvidia_key1", 1.0) == 1.0  # never scaled


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
    # Trading fleet checks are covered by their own tests; isolate this test
    # to the dost services it originally exercised.
    monkeypatch.setattr(heal, "check_trading_fleet_health", lambda m: [])
    monkeypatch.setattr(heal, "check_trading_metrics_health", lambda m: [])
    # Infrastructure is healthy in this scenario: web server and database
    # remediation are exercised by their own tests.
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

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


def test_chaos_provider_failure_triggers_self_healing_failover(monkeypatch):
    """Chaos-injected provider failure plus saturated metrics => pool failover; recovery restores routing.

    Locks the chaos harness (tests/test_chaos.py) together with
    FleetSelfHealing as a recurring regression: a fault-injected pool that is
    saturated in /metrics must be failed over, and once the fault clears and
    saturation drops, the pool must recover.
    """
    reset_failures()
    try:
        fake = FakeMemory()
        monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
        heal = FleetSelfHealing(
            {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
        )

        # Inject a chaos failure on mlx_local and mark its pool saturated.
        inject_provider_failure("mlx_local", 30)
        assert is_provider_failed("mlx_local") is True

        saturated = {"provider_pools": {"mlx_local": {"available": 0, "total": 10}}}  # 100%
        fail_actions = heal.check_pool_saturation(saturated)
        assert len(fail_actions) == 1
        assert fail_actions[0].action_type == "pool_failover"
        assert fail_actions[0].target == "mlx_local"
        assert "mlx_local" in heal._failed_over_pools

        # A failed-over pool is not auto-scaled; failover owns its routing.
        assert heal.check_provider_pool_scaling(saturated) == []

        # Clear the chaos failure and let saturation drop: pool_recover fires.
        clear_provider_failure("mlx_local")
        assert is_provider_failed("mlx_local") is False
        recovered = {"provider_pools": {"mlx_local": {"available": 10, "total": 10}}}  # 0%
        rec_actions = heal.check_pool_saturation(recovered)
        assert len(rec_actions) == 1
        assert rec_actions[0].action_type == "pool_recover"
        assert rec_actions[0].target == "mlx_local"
        assert "mlx_local" not in heal._failed_over_pools
    finally:
        reset_failures()


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
    assert any(
        c[:2] == ["launchctl", "kickstart"]
        and any("com.aryan.dost-proactive-agent" in part for part in c)
        for c in cmds
    ), "kickstart must target the proactive agent label (domain target gui/<uid>/<label>)"


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


# ----------------------- Productionized loop tests -----------------------

def test_cooldown_escalating_backoff_and_cap(monkeypatch):
    """Consecutive failures exponentially back off (capped); success resets."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 10}}
    )

    now = [1000.0]
    monkeypatch.setattr("ops.self_healing.time.time", lambda: now[0])

    key = "pool_failover_x"
    assert heal._should_act(key) is True
    assert heal._should_act(key) is False  # within 10s base cooldown

    # First failure backs off to 20s: 15s elapsed is not enough.
    heal._record_action_outcome(key, False)
    now[0] += 15
    assert heal._should_act(key) is False

    now[0] += 10  # 25s elapsed: past 20s backoff
    assert heal._should_act(key) is True

    # Second failure backs off to 40s.
    heal._record_action_outcome(key, False)
    now[0] += 30
    assert heal._should_act(key) is False

    # A success resets the backoff entirely.
    heal._record_action_outcome(key, True)
    assert heal._consecutive_failures.get(key) is None
    assert heal._should_act(key) is True

    # Four failures cap the multiplier at 8 -> 80s cooldown.
    for _ in range(4):
        heal._record_action_outcome(key, False)
    now[0] += 70
    assert heal._should_act(key) is False
    now[0] += 20
    assert heal._should_act(key) is True


def test_circuit_breaker_persists_across_instances(monkeypatch, tmp_path):
    """A tripped circuit survives a simulated restart via the preference store."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    monkeypatch.setattr(
        "ops.self_healing.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="PID 123", stderr=""),
    )

    heal = FleetSelfHealing(
        {
            "thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0},
            "delivery_channels": ["web"],
        }
    )
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {"provider_pools": {}, "jev": {"error_rate": 99.0}},
    )
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True
    assert heal._circuit_broken is True
    assert fake.prefs["circuit_broken"] is True

    # New instance ("restart") reads the tripped circuit from memory.
    restarted = FleetSelfHealing()
    assert restarted._circuit_broken is True

    # Recovery persists too: a full cycle writes circuit_broken back to memory.
    monkeypatch.setattr(restarted, "fetch_fleet_metrics", lambda: {"provider_pools": {}})
    actions = restarted.check_error_rates({"jev": {"error_rate": 1.0}})  # < 5%
    assert len(actions) == 1
    assert actions[0].action_type == "circuit_recover"
    assert restarted._circuit_broken is False
    result = asyncio.run(restarted.run_once())
    assert result["ok"] is True
    assert fake.prefs["circuit_broken"] is False


def test_remediation_failure_alerts_recorded_and_capped(monkeypatch):
    """Failed remediations become alerts, are queryable via get_alerts, and capped at 200."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing()

    action = HealingAction(
        id="heal-1",
        action_type="service_restart",
        target="com.aryan.dost-monitor",
        reason="kickstart failed",
        timestamp="2026-01-01T00:00:00Z",
        success=False,
        details={"error": "boom"},
    )
    heal._record_remediation_failure_alert(action)

    assert len(heal._alerts) == 1
    assert heal._alerts[0]["action_type"] == "service_restart"
    assert heal._alerts[0]["target"] == "com.aryan.dost-monitor"
    assert fake.prefs["healing_alerts"][0]["reason"] == "kickstart failed"
    assert heal.get_alerts() == heal._alerts[-50:]

    # Cap at 200 entries, persisted.
    for i in range(250):
        heal._record_remediation_failure_alert(
            HealingAction(
                id=f"heal-{i}",
                action_type="service_restart",
                target=f"svc-{i}",
                reason="r",
                timestamp=f"2026-01-01T00:00:{i % 60:02d}Z",
                success=False,
            )
        )
    assert len(heal._alerts) == 200
    assert len(fake.prefs["healing_alerts"]) == 200
    assert heal._alerts[-1]["target"] == "svc-249"
    assert heal.get_alerts(limit=5) == heal._alerts[-5:]


def test_run_once_records_failure_alerts_for_failed_actions(monkeypatch, tmp_path):
    """run_once records a healing alert for every unsuccessful remediation action."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing({"delivery_channels": ["web"]})
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {
            "provider_pools": {"nvidia_key1": {"available": 1, "total": 10}},
            "jev": {"error_rate": 99.0},
        },
    )
    # Kickstart fails for every service: 4 failed dost service restarts.
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=1, list_running=False)
    monkeypatch.setattr(heal, "check_trading_fleet_health", lambda m: [])
    monkeypatch.setattr(heal, "check_trading_metrics_health", lambda m: [])
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True
    failed = [a for a in result["actions"] if not a["success"]]
    assert len(failed) == 4
    assert all(a["type"] == "service_restart" for a in failed)

    alerts = heal.get_alerts()
    restart_alerts = [a for a in alerts if a["action_type"] == "service_restart"]
    assert len(restart_alerts) == 4
    assert {a["target"] for a in restart_alerts} == set(SERVICE_LABELS.values())


def test_run_once_resilient_to_check_failure(monkeypatch, tmp_path):
    """A check that raises never kills the cycle; the failure is logged as an alert."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing({"delivery_channels": ["web"]})
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {
            "provider_pools": {"nvidia_key1": {"available": 1, "total": 10}},  # 90%
            "jev": {"error_rate": 99.0},
        },
    )
    monkeypatch.setattr(
        heal,
        "check_pool_saturation",
        lambda m: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    _fake_subprocess(monkeypatch, restart_rc=0, list_running=False)
    monkeypatch.setattr(heal, "check_trading_fleet_health", lambda m: [])
    monkeypatch.setattr(heal, "check_trading_metrics_health", lambda m: [])
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True
    # check_pool_saturation raised, so no pool_failover; circuit_break, the
    # 4 service restarts still ran, and pool auto-scaling emitted scale_down.
    types = {a["type"] for a in result["actions"]}
    assert types == {"circuit_break", "service_restart", "pool_scale_down"}
    assert len([a for a in result["actions"] if a["type"] == "service_restart"]) == 4
    alerts = heal.get_alerts()
    assert any(
        a["action_type"] == "check_error"
        and a["target"] == "pool_saturation"
        and "kaboom" in a["reason"]
        for a in alerts
    )


def test_remediation_failure_alert_escalation(monkeypatch):
    """Alert is marked escalated when consecutive failures reach the threshold."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing()

    key = "service_restart_com.aryan.dost-monitor"
    action = HealingAction(
        id="heal-1",
        action_type="service_restart",
        target="com.aryan.dost-monitor",
        reason="kickstart failed",
        timestamp="2026-01-01T00:00:00Z",
        success=False,
        details={"error": "boom"},
    )

    # Two failures: below the escalation threshold of 3.
    heal._record_action_outcome(key, False)
    heal._record_action_outcome(key, False)
    heal._record_remediation_failure_alert(action)
    assert heal._alerts[-1]["escalated"] is False
    assert heal._alerts[-1]["consecutive_failures"] == 2
    assert heal._alerts[-1]["action_key"] == key

    # Third failure reaches the threshold: alert is escalated.
    heal._record_action_outcome(key, False)
    heal._record_remediation_failure_alert(action)
    assert heal._alerts[-1]["escalated"] is True
    assert heal._alerts[-1]["consecutive_failures"] == 3


def test_run_once_persists_trading_fleet_and_consecutive_failures(monkeypatch, tmp_path):
    """run_once persists trading fleet snapshot and consecutive-failure counts."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)

    heal = FleetSelfHealing({"delivery_channels": ["web"]})
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}},
    )
    monkeypatch.setattr(
        heal,
        "fetch_trading_fleet_metrics",
        lambda: {
            "fleet_health_ok": {"": 1.0},
            "fleet_agents_alive": {"": 40.0},
            "fleet_agents_expected": {"": 42.0},
        },
    )
    # All four dost services down and restart failing -> one consecutive failure each.
    _fake_subprocess(monkeypatch, restart_rc=1, kickstart_rc=1, list_running=False)
    monkeypatch.setattr(heal, "check_trading_fleet_health", lambda m: [])
    monkeypatch.setattr(heal, "check_trading_metrics_health", lambda m: [])
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True

    assert fake.prefs["trading_fleet"]["fleet_health_ok"][""] == 1.0
    assert fake.prefs["trading_fleet"]["fleet_agents_alive"][""] == 40.0
    assert fake.prefs["trading_fleet"]["fleet_agents_expected"][""] == 42.0

    cf = fake.prefs["consecutive_failures"]
    assert set(cf) == {f"service_restart_{lbl}" for lbl in SERVICE_LABELS.values()}
    assert all(v == 1 for v in cf.values())


def test_self_healing_supervision_catches_run_once_exception(monkeypatch, tmp_path):
    """_run_supervised_once catches a run_once exception and keeps the loop alive."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    heal = FleetSelfHealing()
    monkeypatch.setattr(
        heal,
        "fetch_fleet_metrics",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics blew up")),
    )

    result = asyncio.run(heal._run_supervised_once())

    assert result["ok"] is False
    assert result["supervised"] is True
    assert "metrics blew up" in result["error"]
    assert heal._loop_failures == 1
    assert heal._loop_healthy is False
    assert "metrics blew up" in heal._loop_last_error


def test_self_healing_supervision_resets_on_success(monkeypatch, tmp_path):
    """A successful supervised cycle resets failure tracking to healthy."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    heal = FleetSelfHealing()
    heal._loop_failures = 3
    heal._loop_last_error = "old error"
    heal._loop_healthy = False

    monkeypatch.setattr(
        heal, "fetch_fleet_metrics", lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}}
    )
    monkeypatch.setattr(heal, "fetch_trading_fleet_metrics", lambda: {})
    for check in (
        "check_stuck_tasks",
        "check_pool_saturation",
        "check_provider_pool_scaling",
        "check_error_rates",
        "check_service_health",
        "check_trading_fleet_health",
        "check_trading_metrics_health",
        "check_infrastructure",
        "check_predictive_prehealing",
    ):
        monkeypatch.setattr(heal, check, lambda m: [])

    result = asyncio.run(heal._run_supervised_once())

    assert result["ok"] is True
    assert heal._loop_failures == 0
    assert heal._loop_last_error is None
    assert heal._loop_healthy is True


def test_self_healing_persists_loop_liveness_across_restart(monkeypatch, tmp_path):
    """run_once persists self_healing loop liveness state to memory preferences."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    heal = FleetSelfHealing()
    monkeypatch.setattr(
        heal, "fetch_fleet_metrics", lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}}
    )
    monkeypatch.setattr(heal, "fetch_trading_fleet_metrics", lambda: {})
    for check in (
        "check_stuck_tasks",
        "check_pool_saturation",
        "check_provider_pool_scaling",
        "check_error_rates",
        "check_service_health",
        "check_trading_fleet_health",
        "check_trading_metrics_health",
        "check_infrastructure",
        "check_predictive_prehealing",
    ):
        monkeypatch.setattr(heal, check, lambda m: [])

    # Simulate a degraded supervision state, then run a cycle to persist it.
    heal._loop_failures = 2
    heal._loop_last_error = "kaboom"
    heal._loop_healthy = False

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True

    assert fake.prefs["self_healing_loop_failures"] == 2
    assert fake.prefs["self_healing_loop_last_error"] == "kaboom"
    assert fake.prefs["self_healing_loop_healthy"] is False


def test_escalation_alert_sent_only_when_escalated(monkeypatch):
    """_send_healing_alert fires only for escalated (>= threshold) failures."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    heal = FleetSelfHealing({"delivery_channels": ["telegram", "web", "memory"]})

    telegram_sent: list = []

    async def fake_telegram(alert):
        telegram_sent.append(alert)

    monkeypatch.setattr(heal, "_send_telegram_healing_alert", fake_telegram)

    key = "service_restart_com.aryan.dost-monitor"
    action = HealingAction(
        id="heal-1",
        action_type="service_restart",
        target="com.aryan.dost-monitor",
        reason="kickstart failed",
        timestamp="2026-01-01T00:00:00Z",
        success=False,
        details={"error": "boom"},
    )

    # Two failures: below the escalation threshold of 3 -> not sent.
    heal._record_action_outcome(key, False)
    heal._record_action_outcome(key, False)
    alert = heal._record_remediation_failure_alert(action)
    assert alert["escalated"] is False
    asyncio.run(heal._send_healing_alert(alert))
    assert telegram_sent == []

    # Third failure reaches the threshold: escalated -> sent via Telegram.
    heal._record_action_outcome(key, False)
    alert = heal._record_remediation_failure_alert(action)
    assert alert["escalated"] is True
    asyncio.run(heal._send_healing_alert(alert))
    assert len(telegram_sent) == 1
    assert telegram_sent[0]["escalated"] is True
    assert telegram_sent[0]["consecutive_failures"] == 3

