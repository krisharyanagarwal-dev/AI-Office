"""Tests for the JEV dispatcher's deterministic logic (no model calls).

Tests the state bundle gatherer, verdict gate, and compliance verification
against ground-truth fixtures — everything a model should not be trusted with.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Ensure the office-os package is importable (dispatcher imports from core.*).
sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")

# Load the dispatcher module from its hyphenated filename.
_DISPATCHER_PATH = "/Users/aryanagarwal/.openclaw/jev-dispatcher.py"
_spec = importlib.util.spec_from_file_location("jev_dispatcher", _DISPATCHER_PATH)
jev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jev)  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: write temporary ground-truth files the dispatcher reads
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_env(monkeypatch):
    """Point the dispatcher at temporary files instead of real ones."""
    tmp = tempfile.mkdtemp()
    ks_path = Path(tmp) / "trader_killswitch_status.json"
    cfg_path = Path(tmp) / "office.json"

    kill_switch = {
        "ts": "2026-11-16T05:30:00Z",
        "label": "com.aryan.openalice-alphainsider-trader",
        "verdict": "LOCKED",
        "drift_count": 0,
        "findings": [
            {"ok": True, "check": "code default is '0'"},
            {"ok": True, "check": "installed plist disabled"},
            {"ok": True, "check": "job not loaded, no trader process"},
            {"ok": True, "check": "approval marker absent"},
        ],
    }
    office_config = {
        "autonomy": {
            "executor_enabled": False,
            "forbidden_path_patterns": [".env", "*key*", "*secret*", "*token*", "live_orders", "order", "executor"],
        }
    }
    ks_path.write_text(json.dumps(kill_switch))
    cfg_path.write_text(json.dumps(office_config))

    monkeypatch.setattr(jev, "KILL_SWITCH_PATH", str(ks_path))
    monkeypatch.setattr(jev, "OFFICE_CONFIG_PATH", str(cfg_path))
    return tmp


# ---------------------------------------------------------------------------
# verify_compliance_output
# ---------------------------------------------------------------------------

def test_compliance_passes_when_locked_and_executor_off(tmp_env):
    issues = jev.verify_compliance_output("compliance-checker", "kill switch is LOCKED, PASS")
    assert issues == []


def test_compliance_fails_when_kill_switch_not_locked(tmp_env, monkeypatch):
    tmp = tmp_env
    ks_path = Path(tmp) / "trader_killswitch_status.json"
    ks_path.write_text(json.dumps({"verdict": "DRIFT", "drift_count": 2}))
    issues = jev.verify_compliance_output("compliance-checker", "kill switch status unknown")
    assert any("LOCKED" in i for i in issues)


def test_compliance_fails_when_executor_enabled(tmp_env, monkeypatch):
    tmp = tmp_env
    cfg_path = Path(tmp) / "office.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["autonomy"]["executor_enabled"] = True
    cfg_path.write_text(json.dumps(cfg))
    issues = jev.verify_compliance_output("compliance-checker", "kill switch LOCKED, PASS")
    assert any("executor_enabled" in i for i in issues)


def test_compliance_fails_when_forbidden_patterns_missing(tmp_env, monkeypatch):
    tmp = tmp_env
    cfg_path = Path(tmp) / "office.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["autonomy"]["forbidden_path_patterns"] = [".env"]  # no order/executor
    cfg_path.write_text(json.dumps(cfg))
    issues = jev.verify_compliance_output("compliance-checker", "kill switch LOCKED, PASS")
    assert any("forbidden_path_patterns" in i for i in issues)


# ---------------------------------------------------------------------------
# verdict_gate
# ---------------------------------------------------------------------------

def test_verdict_gate_passes_with_verdict_keyword():
    ok, reason = jev.verdict_gate("market-data-analyst", "VERDICT: PASS — all sources healthy.", "")
    assert ok is True
    assert reason == "passes deterministic gate"


def test_verdict_gate_blocks_without_verdict_keyword():
    ok, reason = jev.verdict_gate("market-data-analyst", "The data sources look fine, I think.", "")
    assert ok is False
    assert "verdict keyword" in reason


def test_verdict_gate_compliance_requires_locked():
    ok, reason = jev.verdict_gate("compliance-checker", "VERDICT: PASS — everything looks good.", "")
    assert ok is False
    assert "kill switch" in reason


def test_verdict_gate_risk_requires_limits():
    ok, reason = jev.verdict_gate("risk-control-verifier", "VERDICT: PASS — kill switch LOCKED.", "")
    assert ok is False
    assert "risk" in reason.lower()


def test_verdict_gate_risk_passes_with_limits():
    ok, reason = jev.verdict_gate(
        "risk-control-verifier",
        "VERDICT: PASS — kill switch LOCKED, max heat 6%, 3 concurrent legs, drawdown tiers active.",
        "",
    )
    assert ok is True


# ---------------------------------------------------------------------------
# gather_state_bundle (agent without mapped state returns None)
# ---------------------------------------------------------------------------

def test_gather_state_bundle_unknown_agent_returns_none():
    assert jev.gather_state_bundle("nonexistent-agent", "pro") is None


def test_gather_state_bundle_compliance_reads_files(tmp_env, monkeypatch):
    # Point AGENT_STATE_FILES at our temp files
    monkeypatch.setitem(
        jev.AGENT_STATE_FILES,
        "compliance-checker",
        [
            ("kill_switch_status", str(Path(tmp_env) / "trader_killswitch_status.json")),
            ("office_config", str(Path(tmp_env) / "office.json")),
        ],
    )
    bundle = jev.gather_state_bundle("compliance-checker", "lite")
    assert bundle is not None
    assert "LOCKED" in bundle
    assert "executor_enabled" in bundle

# ---------------------------------------------------------------------------
# add_finding dedup
# ---------------------------------------------------------------------------

def test_add_finding_dedupes_by_agent_and_claim(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    added1 = jev.add_finding("compliance-checker", "kill switch LOCKED", "jev-task-abc", "supported")
    added2 = jev.add_finding("compliance-checker", "kill switch LOCKED", "jev-task-def", "supported")
    assert added1 is True
    assert added2 is False  # duplicate claim+agent

    store = json.loads(store_path.read_text())
    assert len(store["findings"]) == 1
    assert store["findings"][0]["agent"] == "compliance-checker"
    assert store["findings"][0]["verdict"] == "supported"


# ---------------------------------------------------------------------------
# synthesize_cycle
# ---------------------------------------------------------------------------

def test_synthesize_cycle_empty_returns_none(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({"findings": []}))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    assert jev.synthesize_cycle() is None


def test_synthesize_cycle_all_supported(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [
            {"agent": "compliance-checker", "claim": "kill switch LOCKED",
             "verdict": "supported", "date": "2026-11-16T05:00:00Z"},
            {"agent": "risk-control-verifier", "claim": "heat 6%, 3 legs",
             "verdict": "supported", "date": "2026-11-16T05:01:00Z"},
        ]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    summary = jev.synthesize_cycle()
    assert summary is not None
    assert "ALL-CLEAR" in summary
    assert "confidence 100%" in summary
    assert "2/2 findings supported" in summary


def test_synthesize_cycle_with_blocked(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [
            {"agent": "compliance-checker", "claim": "kill switch LOCKED",
             "verdict": "supported", "date": "2026-11-16T05:00:00Z"},
            {"agent": "risk-control-verifier", "claim": "drawdown tier breached",
             "verdict": "needs-review", "date": "2026-11-16T05:01:00Z"},
        ]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    summary = jev.synthesize_cycle()
    assert summary is not None
    assert "CAUTION" in summary
    assert "risk-control-verifier" in summary


def test_synthesize_cycle_writes_report(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [
            {"agent": "compliance-checker", "claim": "kill switch LOCKED",
             "verdict": "supported", "date": "2026-11-16T05:00:00Z"},
        ]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    summary = jev.synthesize_cycle()
    assert summary is not None
    assert "ALL-CLEAR" in summary
    assert "confidence 100%" in summary
    assert "1/1 findings supported" in summary


# ---------------------------------------------------------------------------
# update_finding_outcome + findings_summary (Track Record)
# ---------------------------------------------------------------------------

def test_update_finding_outcome_marks_right(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [
            {"id": "f-abc12345", "agent": "compliance-checker",
             "claim": "kill switch LOCKED", "verdict": "supported",
             "date": "2026-11-16T05:00:00Z"},
        ]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    assert jev.update_finding_outcome("f-abc12345", "right") is True
    store = json.loads(store_path.read_text())
    assert store["findings"][0]["outcome"] == "right"
    assert "outcome_date" in store["findings"][0]


def test_update_finding_outcome_unknown_id_returns_false(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({"findings": []}))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    assert jev.update_finding_outcome("f-nonexistent", "wrong") is False


def test_findings_summary_aggregate(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [
            {"id": "f-1", "agent": "compliance-checker",
             "claim": "kill switch LOCKED", "verdict": "supported",
             "date": "2026-11-16T05:00:00Z", "outcome": "right"},
            {"id": "f-2", "agent": "risk-control-verifier",
             "claim": "drawdown tier breached", "verdict": "needs-review",
             "date": "2026-11-16T05:01:00Z", "outcome": "wrong"},
            {"id": "f-3", "agent": "compliance-checker",
             "claim": "executor_enabled false", "verdict": "supported",
             "date": "2026-11-16T05:02:00Z"},
        ]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    s = jev.findings_summary()
    assert s["total_findings"] == 3
    assert s["verdicts"]["supported"] == 2
    assert s["verdicts"]["needs-review"] == 1
    assert s["outcomes"]["right"] == 1
    assert s["outcomes"]["wrong"] == 1
    assert s["outcomes"]["pending"] == 1
    assert s["decided"] == 2
    assert s["hit_rate"] == 50.0
    assert s["by_agent"]["compliance-checker"] == 2
    assert s["by_agent"]["risk-control-verifier"] == 1


def test_findings_summary_empty(monkeypatch):
    tmp = tempfile.mkdtemp()
    store_path = Path(tmp) / "findings.json"
    store_path.write_text(json.dumps({"findings": []}))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))
    s = jev.findings_summary()
    assert s["total_findings"] == 0
    assert s["hit_rate"] == 0
    assert s["decided"] == 0


# ---------------------------------------------------------------------------
# cache gate
# ---------------------------------------------------------------------------

def test_cache_check_no_entry(monkeypatch):
    monkeypatch.setattr(jev, "_cache_state", {})
    skip, reason = jev.cache_check("compliance-checker", [])
    assert skip is False
    assert reason == "no cache entry"


def test_cache_check_ttl_expired(monkeypatch, tmp_path):
    # Create a temp state file
    state_file = tmp_path / "kill_switch.json"
    state_file.write_text('{"verdict": "LOCKED"}')
    mtime = jev._file_mtime(str(state_file))

    # Cache entry with old timestamp
    jev._cache_state["compliance-checker"] = {
        "mtimes": {str(state_file): mtime},
        "finding_id": "f-abc",
        "ts": time.time() - 400,  # older than CACHE_TTL_SEC (300s)
    }
    skip, reason = jev.cache_check(
        "compliance-checker", [("kill_switch", str(state_file))]
    )
    assert skip is False
    assert reason == "cache TTL expired"


def test_cache_check_inputs_unchanged(monkeypatch, tmp_path):
    state_file = tmp_path / "kill_switch.json"
    state_file.write_text('{"verdict": "LOCKED"}')
    mtime = jev._file_mtime(str(state_file))

    # Also need a finding in the store
    store_path = tmp_path / "findings.json"
    store_path.write_text(
        json.dumps({"findings": [{"agent": "compliance-checker", "claim": "x"}]})
    )
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    jev._cache_state["compliance-checker"] = {
        "mtimes": {str(state_file): mtime},
        "finding_id": "f-abc",
        "ts": time.time(),
    }
    skip, reason = jev.cache_check(
        "compliance-checker", [("kill_switch", str(state_file))]
    )
    assert skip is True
    assert reason == "inputs unchanged, finding exists"


def test_cache_check_source_changed(monkeypatch, tmp_path):
    state_file = tmp_path / "kill_switch.json"
    state_file.write_text('{"verdict": "LOCKED"}')
    mtime1 = jev._file_mtime(str(state_file))

    store_path = tmp_path / "findings.json"
    store_path.write_text(
        json.dumps({"findings": [{"agent": "compliance-checker", "claim": "x"}]})
    )
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    jev._cache_state["compliance-checker"] = {
        "mtimes": {str(state_file): mtime1 - 100},  # pretend older mtime
        "finding_id": "f-abc",
        "ts": time.time(),
    }
    # Actually change the file
    import time as _time
    _time.sleep(0.01)
    state_file.write_text('{"verdict": "DRIFT"}')
    mtime2 = jev._file_mtime(str(state_file))

    skip, reason = jev.cache_check(
        "compliance-checker", [("kill_switch", str(state_file))]
    )
    assert skip is False
    assert "source changed" in reason


def test_cache_update_records_state(tmp_path):
    state_file = tmp_path / "kill_switch.json"
    state_file.write_text('{"verdict": "LOCKED"}')
    jev._cache_state = {}
    jev.cache_update("compliance-checker", [("kill_switch", str(state_file))], "f-123")
    cached = jev._cache_state["compliance-checker"]
    assert cached["finding_id"] == "f-123"
    assert cached["mtimes"][str(state_file)] == jev._file_mtime(str(state_file))


# ---------------------------------------------------------------------------
# stampede protection
# ---------------------------------------------------------------------------

def test_stampede_acquire_release():
    jev._stampede_locks = {}
    assert jev.stampede_acquire("agent-a") is True
    assert jev.stampede_acquire("agent-a") is False  # already locked
    assert jev.stampede_acquire("agent-b") is True  # different agent OK
    jev.stampede_release("agent-a")
    assert jev.stampede_acquire("agent-a") is True  # released, can acquire again


def test_stampede_acquire_ttl_expires(monkeypatch):
    jev._stampede_locks = {}
    assert jev.stampede_acquire("agent-a") is True
    # Manually set old timestamp
    jev._stampede_locks["agent-a"] = time.time() - 400  # older than default 300s TTL
    assert jev.stampede_acquire("agent-a") is True  # TTL expired, can re-acquire

