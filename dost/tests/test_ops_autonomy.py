"""Tests for dost ops autonomy modules (anomaly watch, self-healing,
opportunity scanner, proactive scheduler, proactive agent).

Covers the config-merge fix (partial orchestrator config keeps default
tables) and graceful degradation when external dependencies are unavailable.
"""

from __future__ import annotations

import asyncio

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


def test_self_healing_pool_saturation_triggers_failover(monkeypatch):
    """Saturated pool produces a pool_failover healing action."""
    fake = FakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)

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
