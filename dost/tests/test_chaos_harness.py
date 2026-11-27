"""
Chaos/fault-injection harness for the Dost dispatch path.

Integrates the fault-injection library in tests/test_chaos.py with the real
ProviderRouter (packages/office-os/core/router.py): provider failures are
injected and the router must fail over or degrade instead of crashing.

Paper/testnet-only: no model calls, no credentials, no live order paths.

Run: python -m pytest dost/tests/test_chaos_harness.py -q   (from AI-Office/)
"""

from __future__ import annotations

from pathlib import Path

import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest

# Make `tests.test_chaos` importable regardless of invocation directory.
# `dost/tests/` has no __init__.py, so `tests` resolves as a namespace package
# only when its parent (`dost/`) is on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# Make `core.router` importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "office-os"))

from core.router import ProviderRouter  # noqa: E402

# Load tests/test_chaos.py by file path: sys.path carries multiple `tests`
# packages (notably packages/office-os/tests) that shadow the dost tests dir,
# so a plain `from tests.test_chaos import` would bind the wrong module.
import importlib.util as _importlib_util

_chaos_path = os.path.join(os.path.dirname(__file__), "test_chaos.py")
_chaos_spec = _importlib_util.spec_from_file_location("dost_tests_test_chaos", _chaos_path)
_chaos_mod = _importlib_util.module_from_spec(_chaos_spec)
_chaos_spec.loader.exec_module(_chaos_mod)  # type: ignore[union-attr]

inject_provider_failure = _chaos_mod.inject_provider_failure
is_provider_failed = _chaos_mod.is_provider_failed
clear_provider_failure = _chaos_mod.clear_provider_failure
reset_failures = _chaos_mod.reset_failures
run_chaos_test = _chaos_mod.run_chaos_test
check_graceful_degradation = _chaos_mod.check_graceful_degradation

from ops.self_healing import FleetSelfHealing, HealingAction, HEALING_CONFIG  # noqa: E402


@pytest.fixture(autouse=True)
def _chaos_hygiene():
    """Clear injected failures before and after every test."""
    reset_failures()
    yield
    reset_failures()


def _fresh_router(monkeypatch, tmp_path):
    """Router backed by a hermetic state dir (never touches the real state file)."""
    monkeypatch.setenv("OFFICE_OS_HOME", str(tmp_path / "office-os"))
    return ProviderRouter()


def _chaos_aware_dispatch(router):
    """Dispatch wrapper mirroring production failover under injected chaos.

    Picks the first available pool that is not under an injected failure,
    falling back through the configured fallback chain. Returns a degraded
    result instead of raising when nothing is available.
    """

    def dispatch(prompt: str = "chaos probe") -> dict:
        tried = set()
        for pool_name in list(router.get_all_pools()) + list(router.fallback_chain):
            if pool_name in tried:
                continue
            tried.add(pool_name)
            if not router.is_available(pool_name):
                continue
            if is_provider_failed(pool_name):
                continue
            model = router._round_robin_model(pool_name)
            return {
                "ok": True,
                "provider": pool_name,
                "model": model,
                "response": f"chaos probe served by {pool_name}",
            }
        return {"ok": False, "degraded": True, "error": "all providers unavailable", "provider": None}

    return dispatch


def test_chaos_injected_failure_expires(monkeypatch, tmp_path):
    """Injected failures expire after their duration and purge themselves."""
    router = _fresh_router(monkeypatch, tmp_path)
    inject_provider_failure("mlx_local", 1)
    assert is_provider_failed("mlx_local") is True
    time.sleep(1.1)
    assert is_provider_failed("mlx_local") is False


def test_chaos_single_pool_failure_fails_over(monkeypatch, tmp_path):
    """One failed pool must not take down dispatch; another pool answers."""
    router = _fresh_router(monkeypatch, tmp_path)
    dispatch = _chaos_aware_dispatch(router)

    inject_provider_failure("mlx_local", 10)
    result = dispatch()

    assert result["ok"] is True
    assert result["provider"] != "mlx_local"
    assert "model" in result and result["model"]


def test_chaos_all_pools_failed_returns_degraded_instead_of_crashing(monkeypatch, tmp_path):
    """Every pool failed: dispatch degrades (ok=False) rather than raising."""
    router = _fresh_router(monkeypatch, tmp_path)
    dispatch = _chaos_aware_dispatch(router)

    for pool_name in router.get_all_pools():
        inject_provider_failure(pool_name, 10)

    result = dispatch()  # must not raise
    assert result["ok"] is False
    assert result.get("degraded") is True
    assert result["provider"] is None


def test_chaos_run_chaos_test_battery_never_crashes(monkeypatch, tmp_path):
    """run_chaos_test across every pool: all scenarios pass, none crash."""
    router = _fresh_router(monkeypatch, tmp_path)
    dispatch = _chaos_aware_dispatch(router)

    scenarios = [{"provider": name, "duration": 5} for name in router.get_all_pools()]
    summary = run_chaos_test(dispatch, scenarios)

    assert summary["total_tests"] == len(scenarios)
    assert summary["failed"] == 0
    assert summary["passed"] == len(scenarios)
    for r in summary["results"]:
        assert r["passed"] is True
        assert r["error"] is None


def test_chaos_check_graceful_degradation(monkeypatch, tmp_path):
    """check_graceful_degradation: the wrapper degrades instead of crashing."""
    router = _fresh_router(monkeypatch, tmp_path)
    dispatch = _chaos_aware_dispatch(router)

    verdict = check_graceful_degradation(dispatch)
    assert verdict["degraded_gracefully"] is True
    assert len(verdict["details"]) == 3


def test_chaos_fleet_dispatch_resilient_under_provider_failure(monkeypatch, tmp_path):
    """Fleet submission (dry_run) keeps working while every provider fails."""
    router = _fresh_router(monkeypatch, tmp_path)
    from dost import dost_main  # noqa: E402

    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    for pool_name in router.get_all_pools():
        inject_provider_failure(pool_name, 10)

    for i in range(5):
        result = dost_main.dispatch_prompt_to_fleet(
            f"chaos probe {i}", agent_id="strategy-advisor", dry_run=True
        )
        assert result["ok"] is True
        assert result["dry_run"] is True


# ----------------------- Trading fleet chaos tests -----------------------

class _ChaosFakeMemory:
    """In-memory stand-in for the unified memory layer."""

    def __init__(self) -> None:
        self.prefs: dict = {}
        self.messages: list = []

    def get_preference(self, key, default=None):
        return self.prefs.get(key, default)

    def set_preference(self, key, value) -> None:
        self.prefs[key] = value

    def add_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))


def _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0):
    """Stub launchctl: 'list' reports running status; kickstart returns given rc."""

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["launchctl", "list"]:
            return SimpleNamespace(
                returncode=0 if list_running else 1,
                stdout="PID 123" if list_running else "",
                stderr="",
            )
        if cmd[:2] == ["launchctl", "kickstart"]:
            return SimpleNamespace(returncode=kickstart_rc, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("ops.self_healing.subprocess.run", fake_run)


def _chaos_trading_heal(monkeypatch, tmp_path):
    """Hermetic FleetSelfHealing for trading fleet chaos tests."""
    fake = _ChaosFakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )
    return heal, fake


def test_chaos_injected_trading_bot_failure_triggers_restart(monkeypatch, tmp_path):
    """Chaos-injected trading_bot failure: down launchd service is restarted."""
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    inject_provider_failure("trading_bot", 30)
    assert is_provider_failed("trading_bot") is True

    actions = heal.check_trading_fleet_health({})
    assert len(actions) == 2
    assert all(a.action_type == "service_restart" for a in actions)
    assert {a.target for a in actions} == {
        "com.aryan.trading-bot",
        "com.aryan.fleet-metrics",
    }
    assert all(a.success for a in actions)
    assert all("not running; restarting" in a.reason for a in actions)
    assert heal._service_heartbeats["com.aryan.trading-bot"]["status"] == "healthy"


def test_chaos_degraded_trading_metrics_restart_trading_bot(monkeypatch, tmp_path):
    """Degraded fleet_metrics exporter output under chaos restarts the trading bot."""
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    inject_provider_failure("trading_bot", 30)
    inject_provider_failure("fleet_metrics", 30)
    assert is_provider_failed("trading_bot") is True
    assert is_provider_failed("fleet_metrics") is True

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


def test_chaos_service_and_metrics_checks_remediate_independently(monkeypatch, tmp_path):
    """Under chaos, service health and metrics health checks fire separate restarts.

    Each check uses its own cooldown key, so a down service and degraded metrics
    both produce remediation in the same cycle instead of one suppressing the other.
    """
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    inject_provider_failure("trading_bot", 30)
    inject_provider_failure("fleet_metrics", 30)

    trading_metrics = {"fleet_health_ok": {"": 0.0}}

    svc_actions = heal.check_trading_fleet_health({})
    metric_actions = heal.check_trading_metrics_health(trading_metrics)

    assert {a.target for a in svc_actions} == {
        "com.aryan.trading-bot",
        "com.aryan.fleet-metrics",
    }
    assert all(a.success for a in svc_actions)
    assert len(metric_actions) == 1
    assert metric_actions[0].target == "com.aryan.trading-bot"
    assert metric_actions[0].success is True


def test_chaos_trading_fleet_recovery(monkeypatch, tmp_path):
    """After chaos clears and metrics recover: no restart, healthy heartbeat."""
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=True, kickstart_rc=1)

    inject_provider_failure("trading_bot", 30)
    assert is_provider_failed("trading_bot") is True

    # Chaos active but service running: service health check takes no action.
    assert heal.check_trading_fleet_health({}) == []

    # Healthy metrics: heartbeat recorded healthy, no remediation.
    healthy_metrics = {
        "fleet_health_ok": {"": 1.0},
        "fleet_checks_failing": {"": 0.0},
        "fleet_agents_alive": {"": 42.0},
        "fleet_agents_expected": {"": 42.0},
    }
    assert heal.check_trading_metrics_health(healthy_metrics) == []
    assert heal._service_heartbeats["com.aryan.trading-bot"]["status"] == "healthy"

    # Chaos clears: provider no longer failed.
    clear_provider_failure("trading_bot")
    assert is_provider_failed("trading_bot") is False


def test_chaos_run_once_trading_fleet_degraded_end_to_end(monkeypatch, tmp_path):
    """run_once wires chaos-observed trading degradation into trading bot restart."""
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)

    inject_provider_failure("trading_bot", 30)
    assert is_provider_failed("trading_bot") is True

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
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)
    monkeypatch.setattr(heal, "_restart_web_server", lambda: None)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    result = asyncio.run(heal.run_once())

    assert result["ok"] is True
    types = {a["type"] for a in result["actions"]}
    assert "service_restart" in types
    trading = [a for a in result["actions"] if a["target"] == "com.aryan.trading-bot"]
    assert len(trading) == 2  # service-health restart + metrics-health restart
    assert any("degraded" in a["reason"] for a in trading)
    assert fake.prefs["service_heartbeats"]["com.aryan.trading-bot"]["status"] == "healthy"


def test_chaos_trading_fleet_battery_never_crashes(monkeypatch, tmp_path):
    """run_chaos_test battery across trading fleet services: dispatch degrades, never crashes."""
    heal, fake = _chaos_trading_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    def dispatch(prompt: str = "chaos probe") -> dict:
        if is_provider_failed("trading_bot"):
            return {"ok": False, "degraded": True, "provider": "trading_bot"}
        return {"ok": True, "provider": "trading_bot"}

    scenarios = [
        {"provider": "trading_bot", "duration": 5},
        {"provider": "fleet_metrics", "duration": 5},
    ]
    summary = run_chaos_test(dispatch, scenarios)

    assert summary["total_tests"] == len(scenarios)
    assert summary["failed"] == 0
    assert summary["passed"] == len(scenarios)
    for r in summary["results"]:
        assert r["passed"] is True
        assert r["error"] is None
        if r["provider"] == "trading_bot":
            assert r["response"]["degraded"] is True


# ----------------------- Infrastructure remediation chaos tests -----------------------

def _chaos_infra_heal(monkeypatch, tmp_path):
    """Hermetic FleetSelfHealing for infrastructure chaos tests."""
    fake = _ChaosFakeMemory()
    monkeypatch.setattr("ops.self_healing.get_unified_memory", lambda: fake)
    monkeypatch.setattr("ops.self_healing.HIVE_DIR", tmp_path)
    heal = FleetSelfHealing(
        {"thresholds": {**HEALING_CONFIG["thresholds"], "cooldown_sec": 0}}
    )
    return heal, fake


def _HealingAction(**kw):
    """Minimal HealingAction builder for faked leaf remediation methods."""
    defaults = dict(
        id="heal-fake",
        action_type="fake",
        target="fake",
        reason="fake",
        timestamp="1970-01-01T00:00:00+00:00",
        success=True,
        details={},
    )
    defaults.update(kw)
    return HealingAction(**defaults)


def test_chaos_disk_pressure_triggers_cleanup(monkeypatch, tmp_path):
    """Disk usage above threshold under chaos triggers disk cleanup."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_disk_usage", lambda: (95.0, "/"))

    saw = {}
    def fake_cleanup(usage_pct):
        saw["pct"] = usage_pct
        return _HealingAction(
            action_type="disk_cleanup",
            target="root_filesystem",
            reason="disk cleanup",
            success=True,
            details={"usage_pct": usage_pct, "freed_mb": 0.0},
        )
    monkeypatch.setattr(heal, "_cleanup_disk", fake_cleanup)

    actions = heal.check_infrastructure({})
    disk_actions = [a for a in actions if a.action_type == "disk_cleanup"]
    assert len(disk_actions) == 1
    assert saw["pct"] == 95.0
    assert disk_actions[0].success is True


def test_chaos_disk_below_threshold_no_cleanup(monkeypatch, tmp_path):
    """Disk usage below threshold under chaos: no cleanup action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_disk_usage", lambda: (50.0, "/"))

    calls = []
    monkeypatch.setattr(
        heal,
        "_cleanup_disk",
        lambda pct: calls.append(pct) or _HealingAction(action_type="disk_cleanup"),
    )

    actions = heal.check_infrastructure({})
    assert calls == []
    assert all(a.action_type != "disk_cleanup" for a in actions)


def test_chaos_memory_pressure_triggers_action(monkeypatch, tmp_path):
    """Memory usage above threshold under chaos triggers memory pressure action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_memory_usage", lambda: 95.0)

    saw = {}
    def fake_handle(pct):
        saw["pct"] = pct
        return _HealingAction(
            action_type="memory_pressure",
            target="system_memory",
            reason="memory pressure",
            success=True,
            details={"usage_pct": pct},
        )
    monkeypatch.setattr(heal, "_handle_memory_pressure", fake_handle)

    actions = heal.check_infrastructure({})
    mem_actions = [a for a in actions if a.action_type == "memory_pressure"]
    assert len(mem_actions) == 1
    assert saw["pct"] == 95.0


def test_chaos_memory_below_threshold_no_action(monkeypatch, tmp_path):
    """Memory usage below threshold under chaos: no memory pressure action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_memory_usage", lambda: 40.0)

    calls = []
    monkeypatch.setattr(
        heal,
        "_handle_memory_pressure",
        lambda pct: calls.append(pct) or _HealingAction(action_type="memory_pressure"),
    )

    actions = heal.check_infrastructure({})
    assert calls == []
    assert all(a.action_type != "memory_pressure" for a in actions)


def test_chaos_web_server_down_restart(monkeypatch, tmp_path):
    """Web server not running under chaos: restart action fired."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)

    actions = heal.check_infrastructure({})
    web_actions = [a for a in actions if a.action_type == "web_server_restart"]
    assert len(web_actions) == 1
    assert web_actions[0].success is True
    assert web_actions[0].target == "com.aryan.dost-office-web"


def test_chaos_web_server_running_no_restart(monkeypatch, tmp_path):
    """Web server running under chaos: no restart action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    _chaos_fake_subprocess(monkeypatch, list_running=True, kickstart_rc=1)

    actions = heal.check_infrastructure({})
    assert all(a.action_type != "web_server_restart" for a in actions)


def test_chaos_database_missing_recovery_failure(monkeypatch, tmp_path):
    """Database missing/empty under chaos: recovery failure action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(
        heal,
        "_recover_database",
        lambda: _HealingAction(
            action_type="database_recover",
            target="office_os_database",
            reason="database missing",
            success=False,
            details={"database": "/nonexistent/office.db", "recovered": False},
        ),
    )

    actions = heal.check_infrastructure({})
    db_actions = [a for a in actions if a.action_type == "database_recover"]
    assert len(db_actions) == 1
    assert db_actions[0].success is False


def test_chaos_database_accessible_no_recovery(monkeypatch, tmp_path):
    """Database accessible under chaos: no recovery action."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_recover_database", lambda: None)

    actions = heal.check_infrastructure({})
    assert all(a.action_type != "database_recover" for a in actions)


def test_chaos_infra_all_checks_wire_through_run_once(monkeypatch, tmp_path):
    """run_once wires all four infrastructure checks without crashing."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)
    monkeypatch.setattr(heal, "_disk_usage", lambda: (95.0, "/"))
    monkeypatch.setattr(heal, "_memory_usage", lambda: 95.0)
    _chaos_fake_subprocess(monkeypatch, list_running=False, kickstart_rc=0)
    monkeypatch.setattr(
        heal, "_cleanup_disk", lambda pct: _HealingAction(action_type="disk_cleanup", success=True)
    )
    monkeypatch.setattr(
        heal,
        "_handle_memory_pressure",
        lambda pct: _HealingAction(action_type="memory_pressure", success=True),
    )
    monkeypatch.setattr(
        heal,
        "_recover_database",
        lambda: _HealingAction(action_type="database_recover", success=False),
    )
    monkeypatch.setattr(
        heal, "fetch_fleet_metrics", lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}}
    )

    result = asyncio.run(heal.run_once())
    assert result["ok"] is True
    types = {a["type"] for a in result["actions"]}
    assert {
        "disk_cleanup",
        "memory_pressure",
        "web_server_restart",
        "database_recover",
    } <= types


def test_chaos_infra_battery_never_crashes(monkeypatch, tmp_path):
    """CI regression: every infrastructure check combination never crashes."""
    heal, fake = _chaos_infra_heal(monkeypatch, tmp_path)

    def scenario(disk_pct, mem_pct, web_running, db_accessible):
        monkeypatch.setattr(heal, "_disk_usage", lambda: (disk_pct, "/"))
        monkeypatch.setattr(heal, "_memory_usage", lambda: mem_pct)
        _chaos_fake_subprocess(monkeypatch, list_running=web_running, kickstart_rc=0)
        monkeypatch.setattr(
            heal, "_cleanup_disk", lambda pct: _HealingAction(action_type="disk_cleanup", success=True)
        )
        monkeypatch.setattr(
            heal,
            "_handle_memory_pressure",
            lambda pct: _HealingAction(action_type="memory_pressure", success=True),
        )
        monkeypatch.setattr(
            heal,
            "_recover_database",
            lambda: None if db_accessible else _HealingAction(action_type="database_recover", success=False),
        )
        monkeypatch.setattr(
            heal, "fetch_fleet_metrics", lambda: {"provider_pools": {}, "jev": {"error_rate": 1.0}}
        )
        return asyncio.run(heal.run_once())

    for disk_pct in (50.0, 95.0):
        for mem_pct in (40.0, 95.0):
            for web_running in (True, False):
                for db_accessible in (True, False):
                    result = scenario(disk_pct, mem_pct, web_running, db_accessible)
                    assert result["ok"] is True
