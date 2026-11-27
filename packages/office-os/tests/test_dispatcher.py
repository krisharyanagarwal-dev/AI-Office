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
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "office-os"))

# Load the dispatcher module from its hyphenated filename.
_DISPATCHER_PATH = str(Path.home() / ".openclaw" / "jev-dispatcher.py")
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
    assert added1 is not False  # returns finding ID string
    assert added2 is False  # duplicate claim+agent

    store = json.loads(store_path.read_text())
    assert len(store["findings"]) == 1
    assert store["findings"][0]["agent"] == "compliance-checker"
    assert store["findings"][0]["verdict"] == "supported"
    assert store["findings"][0]["verification_status"] == "pending"
    assert store["findings"][0]["verified_by"] is None


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
             "verdict": "supported", "date": "2026-11-16T05:00:00Z",
             "verification_status": "confirmed"},
            {"agent": "risk-control-verifier", "claim": "heat 6%, 3 legs",
             "verdict": "supported", "date": "2026-11-16T05:01:00Z",
             "verification_status": "confirmed"},
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
             "verdict": "supported", "date": "2026-11-16T05:00:00Z",
             "verification_status": "confirmed"},
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


# --- O0.1: extract_finding regression tests ---
def test_extract_finding_echo_rejected():
    echo = "The user wants me to act as JEV executing a direct audit task for agent data-feed-monitor. I need to analyze the STATE BUNDL"
    claim, method = jev.extract_finding(echo)
    assert claim is None
    assert method == "echo"


def test_extract_finding_title_echo_rejected():
    title = "**TITLE:** Trade-Log Archivist – Cost & Edge Validation for Paper-Trading Fleet"
    claim, method = jev.extract_finding(title)
    assert claim is None
    assert method == "echo"


def test_extract_finding_preamble_rejected():
    preamble = "Let me analyze the state bundle carefully to answer the three specific questions."
    claim, method = jev.extract_finding(preamble)
    assert claim is None
    assert method == "echo"


def test_extract_finding_finding_line():
    text = "kill switch LOCKED, drift_count=0\nFINDING: kill switch is LOCKED with no trader process running\nVERDICT: PASS"
    claim, method = jev.extract_finding(text)
    assert method == "finding_line"
    assert claim == "kill switch is LOCKED with no trader process running"


def test_extract_finding_finding_line_last_wins():
    text = "FINDING: first attempt\nmore detail here\nFINDING: corrected final claim about drawdown tier\nVERDICT: PASS"
    claim, method = jev.extract_finding(text)
    assert method == "finding_line"
    assert claim == "corrected final claim about drawdown tier"


def test_extract_finding_substantive_fallback():
    text = "Compliance check: kill switch LOCKED, live_orders_allowed=false, no order path found. VERDICT: PASS"
    claim, method = jev.extract_finding(text)
    assert method == "substantive"
    assert "kill switch" in claim and "LOCKED" in claim


def test_extract_finding_empty_and_none():
    assert jev.extract_finding("") == (None, "none")
    assert jev.extract_finding(None) == (None, "none")


def test_extract_finding_headers_skipped():
    text = "# AUDIT REPORT\n**POSITION SIZING RULES**\n- item one\nlive_orders_allowed=false and executor_enabled=false confirmed. VERDICT: PASS"
    claim, method = jev.extract_finding(text)
    assert method == "substantive"
    assert "live_orders_allowed" in claim


# ---------------------------------------------------------------------------
# O1.2: Tripartite consensus tests
# ---------------------------------------------------------------------------

def test_devil_advisor_excludes_producer_and_checkers(monkeypatch):
    """Devil-advisor must differ from producer and all 3 checkers."""
    config = jev.load_office_config()
    agents = jev.get_all_agents(config)
    agent_ids = {a["agent_id"] for a in agents}

    exclude = {"risk-control-verifier", "strategy-acceptance-verifier", "backtest-auditor", "quant-model-validator"}
    devil = jev._devil_advisor_for("risk", list(exclude))
    assert devil is not None
    assert devil not in exclude
    assert devil in agent_ids


def test_devil_advisor_returns_none_when_all_excluded(monkeypatch):
    """If every agent is excluded, devil_advisor returns None."""
    config = jev.load_office_config()
    agents = jev.get_all_agents(config)
    all_ids = [a["agent_id"] for a in agents]
    devil = jev._devil_advisor_for("default", all_ids)
    assert devil is None


def test_tripartite_non_major_domain_returns_unclear(monkeypatch, tmp_path):
    """Non-major domains (e.g. 'default') fall back to single verification."""
    store_path = Path(tmp_path) / "findings.json"
    store_path.write_text(json.dumps({"findings": []}))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    config = jev.load_office_config()
    result = jev.verify_finding_tripartite("f-test", "some-agent", "default", config)
    assert result == "unclear"


def test_tripartite_consensus_all_confirm(monkeypatch, tmp_path):
    """3/3 confirm -> confirmed."""
    store_path = Path(tmp_path) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [{"id": "f-tri-1", "agent": "risk-manager",
                      "claim": "risk limit valid", "verdict": "supported",
                      "date": "2026-11-17T00:00:00Z"}]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    config = jev.load_office_config()

    # Risk domain checkers (first 3 non-Tier-C, excluding producer "risk-manager"):
    # strategy-acceptance-verifier, drawdown-analyst, exposure-analyst
    # Devil-advisor: risk-control-verifier (first verifier not in exclude list)
    def mock_worker(args):
        agent_id = args[0]["agent_id"]
        if agent_id == "drawdown-analyst":
            return {"exec_text": "VERDICT: confirm", "exec_model": "t", "exec_pool": "t"}
        if agent_id == "risk-control-verifier":
            # Devil-advisor: does NOT contest (allows confirmation)
            return {"exec_text": "VERDICT: confirm", "exec_model": "t", "exec_pool": "t"}
        # strategy-acceptance-verifier and exposure-analyst confirm
        return {"exec_text": "VERDICT: confirm", "exec_model": "t", "exec_pool": "t"}
    monkeypatch.setattr(jev, "execute_agent_worker", mock_worker)

    result = jev.verify_finding_tripartite("f-tri-1", "risk-manager", "risk", config)
    assert result == "confirmed"

    store = json.loads(store_path.read_text())
    f = store["findings"][0]
    assert f["verification_status"] == "confirmed"


def test_tripartite_consensus_devil_overturns(monkeypatch, tmp_path):
    """2/3 confirm but devil-advisor contests -> contested."""
    store_path = Path(tmp_path) / "findings.json"
    store_path.write_text(json.dumps({
        "findings": [{"id": "f-tri-2", "agent": "risk-manager",
                      "claim": "risk limit valid", "verdict": "supported",
                      "date": "2026-11-17T00:00:00Z"}]
    }))
    monkeypatch.setattr(jev, "FINDINGS_STORE_PATH", str(store_path))

    config = jev.load_office_config()

    def mock_worker(args):
        agent_id = args[0]["agent_id"]
        # Checkers: strategy-acceptance-verifier (confirm), drawdown-analyst (confirm),
        # exposure-analyst (contest)
        # Devil-advisor: risk-control-verifier (contest)
        if agent_id == "exposure-analyst":
            return {"exec_text": "VERDICT: contest", "exec_model": "t", "exec_pool": "t"}
        if agent_id == "risk-control-verifier":
            return {"exec_text": "VERDICT: contest", "exec_model": "t", "exec_pool": "t"}
        return {"exec_text": "VERDICT: confirm", "exec_model": "t", "exec_pool": "t"}
    monkeypatch.setattr(jev, "execute_agent_worker", mock_worker)

    result = jev.verify_finding_tripartite("f-tri-2", "risk-manager", "risk", config)
    assert result == "contested"

    store = json.loads(store_path.read_text())
    f = store["findings"][0]
    assert f["verification_status"] == "contested"

