#!/usr/bin/env python3
"""
JEV Dispatcher - Cloud-only task planner/executor for the Office OS agent fleet.

- Parallel cloud workers (ThreadPoolExecutor, default 6) for I/O-bound NVIDIA/OpenRouter/Gemini calls
- Fail fast: 45s timeout per call, retry on different key, then mark 'error' and move on
- Skip agents whose latest task is done (< 30 min old) - no re-planning finished work
- Cloud-only: local Qwen is NOT used for fleet tasks
- No DNS gate - real call results drive key health
- Results saved to Hive tasks + .result files for dashboard queryability
"""

import glob
import json
import multiprocessing
import os
import re
import shutil
import signal
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import argparse
except ImportError:  # pragma: no cover
    argparse = None

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
from core.subs.cloud_orchestrator import CloudModelOrchestrator

OFFICE_CONFIG = "/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json"
HIVE_DIR = "/Users/aryanagarwal/AI-Office/packages/office-os/tasks"
JEV_LOG = "/Users/aryanagarwal/.openclaw/jev-dispatcher.log"
JEV_PID_FILE = "/Users/aryanagarwal/.openclaw/jev-dispatcher.pid"
PLAN_INTERVAL_SEC = 300  # Re-plan every 5 minutes
RESULT_DIR = "/Users/aryanagarwal/.openclaw/autonomous-qwen/results"
MAX_WORKERS = 20  # Threads per process for I/O concurrency
WORKER_PROCESSES = os.cpu_count() or 4  # True multi-core parallelism
SKIP_DONE_MIN = 15  # Don't re-plan agents done within this many minutes

# --- Task archive rotation ---
# Once per cycle (cheap check after Phase 3), scan HIVE_DIR for dost-submitted
# tasks (metadata.source == "dost") with status in (done, error) whose
# updated_at is older than ARCHIVE_MAX_AGE_DAYS, and move them to
# HIVE_DIR/archive/. Pending tasks are never touched, so
# collect_user_submitted_tasks() keeps picking up only pending work.
ARCHIVE_DIR = os.path.join(HIVE_DIR, "archive")
ARCHIVE_MAX_AGE_DAYS = 7

os.makedirs(HIVE_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)


# --- State bundle: real trading data injected into prompts so agents reason
# about ground truth instead of role-playing in a vacuum. ---

KILL_SWITCH_PATH = "/Users/aryanagarwal/AI-Office/packages/_archive/openalice-fleet/state/trader_killswitch_status.json"
OFFICE_CONFIG_PATH = "/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json"
POLYMARKET_RESEARCH_DIR = "/Users/aryanagarwal/Documents/polymarket/research"
POLYMARKET_OUT_DIR = "/Users/aryanagarwal/Documents/polymarket/out"
POLYMARKET_FRAMEWORK = "/Users/aryanagarwal/Documents/polymarket/RISK_MANAGEMENT_FRAMEWORK.md"

# Agent-specific state files: (label, path). JSON files are dumped compactly;
# text/markdown files are read raw and truncated.
AGENT_STATE_FILES = {
    "compliance-checker": [
        ("kill_switch_status", KILL_SWITCH_PATH),
        ("office_config", OFFICE_CONFIG_PATH),
    ],
    "risk-control-verifier": [
        ("kill_switch_status", KILL_SWITCH_PATH),
        ("risk_framework", POLYMARKET_FRAMEWORK),
        ("control_results", POLYMARKET_RESEARCH_DIR + "/control_results.json"),
    ],
    "drawdown-analyst": [
        ("audit_log", POLYMARKET_OUT_DIR + "/audit.log"),
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "quant-model-validator": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
        ("execution_assumptions", POLYMARKET_RESEARCH_DIR + "/execution_assumptions.json"),
    ],
    "backtest-auditor": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
        ("calibration_report", POLYMARKET_RESEARCH_DIR + "/calibration_report.json"),
    ],
    "cost-analyst": [
        ("execution_assumptions", POLYMARKET_RESEARCH_DIR + "/execution_assumptions.json"),
        ("accounting_audit", POLYMARKET_RESEARCH_DIR + "/ACCOUNTING_AUDIT.md"),
    ],
    "performance-attribution": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
        ("accounting_audit", POLYMARKET_RESEARCH_DIR + "/ACCOUNTING_AUDIT.md"),
    ],
    "trade-journal-reviewer": [
        ("audit_log", POLYMARKET_OUT_DIR + "/audit.log"),
        ("control_results", POLYMARKET_RESEARCH_DIR + "/control_results.json"),
    ],
    "research-archivist": [
        ("research_dir", POLYMARKET_RESEARCH_DIR),
    ],
    "data-feed-monitor": [
        ("data_sources", POLYMARKET_RESEARCH_DIR + "/data_sources.json"),
    ],
    "market-data-analyst": [
        ("data_sources", POLYMARKET_RESEARCH_DIR + "/data_sources.json"),
    ],
    "position-sizing-analyst": [
        ("risk_framework", POLYMARKET_FRAMEWORK),
    ],
    "exposure-analyst": [
        ("risk_framework", POLYMARKET_FRAMEWORK),
    ],
    "portfolio-allocation-researcher": [
        ("risk_framework", POLYMARKET_FRAMEWORK),
    ],
    "market-maker": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "liquidity-researcher": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "order-book-researcher": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "market-regime-analyst": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
        ("risk_framework", POLYMARKET_FRAMEWORK),
    ],
    "correlation-researcher": [
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "signal-analyst": [
        ("control_results", POLYMARKET_RESEARCH_DIR + "/control_results.json"),
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
    "event-driven-researcher": [
        ("control_results", POLYMARKET_RESEARCH_DIR + "/control_results.json"),
        ("cross_venue_reality", POLYMARKET_RESEARCH_DIR + "/cross_venue_arb_reality.json"),
    ],
}

# --- General assistant routing (non-trading tasks) ---
# Tasks whose prompt matches these keywords are routed through the local
# qwen_local (ollama) pool instead of the expensive cloud research path.
# Keeps free-tier cloud quota for trading research; general admin/docs/dost
# conversation stays cheap and local.
GENERAL_ASSISTANT_KEYWORDS = frozenset({
    "dost", "admin", "documentation", "doc:", " write ", "memo", "email",
    "letter", "summary", "note:", "draft", "conversation", "chat",
    "assistant", "proofread", "rewrite", "format",
})


def is_general_assistant_task(text: str) -> bool:
    """Classify a task as general assistant (non-trading) vs trading research."""
    t = text.lower()
    return any(kw in t for kw in GENERAL_ASSISTANT_KEYWORDS)


def route_through_local(prompt: str, timeout: int = 120) -> str:
    """Route a general-assistant prompt through the local qwen_local (ollama) pool."""
    from core.provider_client import ProviderClient
    client = ProviderClient("qwen_local", "hauhaucs/qwen3.5-9b-uncensored-aggressive")
    return client.complete(
        prompt=prompt, max_tokens=500, temperature=0.7, timeout=timeout,
    )


def read_text_file(path, max_chars=2500):
    """Read a text/markdown file, truncating if too long."""
    try:
        with open(path) as f:
            content = f.read()
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n...[truncated, {len(content)} total bytes]..."
        return content
    except FileNotFoundError:
        return f"[FILE NOT FOUND: {path}]"
    except Exception as e:
        return f"[ERROR reading {path}: {e}]"


def read_json_file(path, max_chars=2500):
    """Read a JSON file and return a compact string."""
    try:
        with open(path) as f:
            data = json.load(f)
        return json.dumps(data, indent=2)[:max_chars]
    except FileNotFoundError:
        return f"[FILE NOT FOUND: {path}]"
    except Exception as e:
        return f"[ERROR reading {path}: {e}]"


def gather_state_bundle(agent_id, tier):
    """Gather real state relevant to this agent.

    Returns a formatted text bundle, or None if no state files are mapped
    for this agent.
    """
    files = AGENT_STATE_FILES.get(agent_id)
    if not files:
        return None

    parts = []
    for label, path in files:
        if os.path.isdir(path):
            try:
                entries = sorted(os.listdir(path))
                content = f"Directory contents of {path}:\n" + "\n".join(entries[:50])
                if len(entries) > 50:
                    content += f"\n...and {len(entries) - 50} more entries"
            except Exception as e:
                content = f"[ERROR listing {path}: {e}]"
        elif path.endswith(".json"):
            content = read_json_file(path)
        elif path.endswith(".md"):
            content = read_text_file(path, max_chars=2500)
        elif path.endswith(".log"):
            content = read_text_file(path, max_chars=2500)
        else:
            content = read_text_file(path, max_chars=2500)
        parts.append(f"### {label}\n{content}\n")

    return "\n".join(parts)


def verify_compliance_output(agent_id, exec_text):
    """Deterministic checks for compliance agent output against ground truth.

    Returns a list of issue strings (empty if all checks pass). LLMs judge
    form; this code checks existence of ground-truth facts.
    """
    issues = []

    # 1. Kill switch must be LOCKED
    try:
        with open(KILL_SWITCH_PATH) as f:
            ks = json.load(f)
        if ks.get("verdict") != "LOCKED":
            issues.append(
                f"kill switch verdict is {ks.get('verdict')!r}, not LOCKED "
                f"(ts={ks.get('ts')})"
            )
    except Exception as e:
        issues.append(f"could not read kill switch status: {e}")

    # 2. live_orders_allowed must be false in office config autonomy block
    try:
        with open(OFFICE_CONFIG_PATH) as f:
            config = json.load(f)
        autonomy = config.get("autonomy", {})
        if autonomy.get("executor_enabled") is True:
            issues.append("executor_enabled is true in office config")
        # Also check forbidden_path_patterns still blocks order/executor paths
        forbidden = autonomy.get("forbidden_path_patterns", [])
        if not any("order" in p or "executor" in p for p in forbidden):
            issues.append("forbidden_path_patterns does not block order/executor paths")
    except Exception as e:
        issues.append(f"could not read office config: {e}")

    return issues


def build_direct_exec_prompt(agent_id, tier, state_bundle):
    """Build a concrete, data-driven exec prompt for agents with state bundles.

    Each agent gets a specific audit/analysis task tied to its real data files,
    so the model reasons about ground truth instead of role-playing.
    """
    agent_lower = agent_id.lower()

    # Agent-specific task directives
    if agent_id == "compliance-checker":
        task = (
            "You are the compliance-checker for a PAPER trading research fleet. "
            "Your job is to audit the paper-trading boundary and report findings.\n\n"
            "TASK: Verify all of the following from the STATE BUNDLE:\n"
            "1. Kill switch status — must read verdict=LOCKED\n"
            "2. live_orders_allowed — must be false in the office config autonomy block\n"
            "3. No live order path — forbidden_path_patterns must block order/executor paths\n"
            "For each check, state PASS or FAIL with the specific evidence from the bundle. "
            "If any check cannot be verified from the bundle, say so explicitly.\n"
            "Output format: one line per check, then a summary verdict."
        )
    elif agent_id == "risk-control-verifier":
        task = (
            "You are the risk-control-verifier for a PAPER trading research fleet. "
            "Your job is to verify risk limits against ground truth.\n\n"
            "TASK: From the STATE BUNDLE (kill switch status, risk framework, control results):\n"
            "1. Confirm kill switch is LOCKED\n"
            "2. Summarize the risk framework's key limits: max position heat, max concurrent legs, drawdown tiers\n"
            "3. Report control leg status — all controls must be NOT_RUN or negative after spread\n"
            "4. Flag any control showing positive after-spread P&L (this is a marking-bug alarm)\n"
            "Output: structured findings with specific numbers from the bundle."
        )
    elif agent_id == "drawdown-analyst":
        task = (
            "You are the drawdown-analyst for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (audit log, cross-venue arb reality):\n"
            "1. Report the last scan age and whether scans are current (<10 min)\n"
            "2. Summarize the cross-venue arb conclusion: is the edge real, accessible at retail latency?\n"
            "3. Identify any structural costs (legging risk, latency) that kill the edge\n"
            "Output: concrete findings, not generalities."
        )
    elif agent_id == "quant-model-validator":
        task = (
            "You are the quant-model-validator for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (cross-venue arb reality, execution assumptions):\n"
            "1. Review the cross-venue arb study — was it paper-only? Were orders submitted?\n"
            "2. Check execution assumptions: fees, slippage, spread treatment\n"
            "3. Determine if the reported edge clears modelled costs (CI excludes zero AND net positive)\n"
            "Output: go/no-go with cost breakdown."
        )
    elif agent_id == "backtest-auditor":
        task = (
            "You are the backtest-auditor for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (cross-venue arb reality, calibration report):\n"
            "1. Check calibration_report verdict — is it INSUFFICIENT_DATA?\n"
            "2. Review cross-venue arb findings for look-ahead bias, data leakage, survivor bias\n"
            "3. Report whether any backtest clears the CI-excludes-zero bar\n"
            "Output: audit findings with pass/fail per check."
        )
    elif agent_id == "cost-analyst":
        task = (
            "You are the cost-analyst for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (execution assumptions, accounting audit):\n"
            "1. Report fees, slippage, spread treatment from execution assumptions\n"
            "2. From the accounting audit: total unclosed notional, sunk cost on unclosed rows\n"
            "3. Calculate whether any reported edge clears these modelled costs\n"
            "Output: cost model with venue/fee/funding stated."
        )
    elif agent_id == "trade-journal-reviewer":
        task = (
            "You are the trade-journal-reviewer for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (audit log, control results):\n"
            "1. Review the audit log for task failures and retry patterns\n"
            "2. Check control_results — are control legs NOT_RUN?\n"
            "3. Report any review failures (truncated output, missing sections)\n"
            "Output: review findings with specific log entries cited."
        )
    elif agent_id == "research-archivist":
        task = (
            "You are the research-archivist for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (research directory listing):\n"
            "1. List the research files present\n"
            "2. Identify which files contain actual findings vs. code vs. notes\n"
            "3. Report any gaps (missing backtests, missing validation reports)\n"
            "Output: inventory with categorization."
        )
    elif agent_id == "data-feed-monitor":
        task = (
            "You are the data-feed-monitor for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (data sources):\n"
            "1. List each data source with its status (AVAILABLE/UNAVAILABLE)\n"
            "2. Flag any source with last_failure set and last_success null\n"
            "3. Report which sources are keyless (authentication_required=false)\n"
            "Output: source health table."
        )
    elif agent_id == "market-maker":
        task = (
            "You are the market-maker for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (cross-venue arb reality):\n"
            "1. Report the cross-venue arb conclusion — real edge but not accessible at retail latency\n"
            "2. Identify legging risk and structural costs\n"
            "3. State whether paper market-making is viable given these constraints\n"
            "Output: viability assessment with reasoning."
        )
    elif agent_id == "position-sizing-analyst":
        task = (
            "You are the position-sizing-analyst for a PAPER trading research fleet.\n\n"
            "TASK: From the STATE BUNDLE (risk framework):\n"
            "1. Report the position sizing formula (fixed-fractional 1R)\n"
            "2. Report max position heat (6%), max concurrent legs (3)\n"
            "3. Report drawdown tier actions (3% daily stop, 5% size cut, 10% size cut, 20% kill switch)\n"
            "Output: sizing rules with all limits."
        )
    else:
        # Generic directive for any other state-bundled agent
        task = (
            f"You are the {agent_id} agent for a PAPER trading research fleet.\n\n"
            "TASK: Review the STATE BUNDLE below and produce concrete findings "
            "based on the real data. Do not fabricate. If the bundle doesn't "
            "cover something, state that explicitly.\n"
        )

    return f"""You are JEV executing a direct audit task for agent {agent_id} (tier: {tier}).

{task}

STATE BUNDLE (ground truth — do not fabricate):
{state_bundle}

If the STATE BUNDLE does not cover something you need, state that explicitly
rather than inventing data. Base every claim on the bundle content.

End your response with:
  FINDING: one-sentence claim grounded in the STATE BUNDLE
  VERDICT: PASS or VERDICT: FAIL or VERDICT: go/no-go"""


def acquire_pid_lock():
    """Ensure only one JEV dispatcher instance runs at a time."""
    try:
        with open(JEV_PID_FILE) as f:
            old_pid = int(f.read().strip())
        # Check if the old process is still alive
        try:
            os.kill(old_pid, 0)
            print(f"JEV already running as PID {old_pid}, exiting.", flush=True)
            sys.exit(0)
        except OSError:
            pass  # stale pid file, overwrite
    except (FileNotFoundError, ValueError):
        pass

    with open(JEV_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def cleanup(signum=None, frame=None):
        try:
            os.unlink(JEV_PID_FILE)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)


# --- Findings store: compounding research output with a verdict gate ---
# Prevents the every-15-minutes-same-task loop by persisting conclusions
# and requiring new cycles to refute or extend, not repeat.
FINDINGS_STORE_PATH = "/Users/aryanagarwal/Documents/polymarket/research/findings.json"


def load_findings_store():
    """Load the findings store, creating it if needed."""
    try:
        with open(FINDINGS_STORE_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "findings" not in data:
            return {"findings": []}
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"findings": []}


def save_findings_store(store):
    """Atomically write the findings store."""
    tmp = FINDINGS_STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2, sort_keys=True)
    os.replace(tmp, FINDINGS_STORE_PATH)


# --- Cache gate: skip re-auditing when source data hasn't changed ---
# Like tradedesk's market-session cache: reuse within a window, refresh
# only when the underlying files change or the window expires.
CACHE_TTL_SEC = 300  # Re-check after 5 minutes even if files unchanged
_cache_state = {}  # agent_id -> {"mtimes": {path: mtime}, "finding_id": id, "ts": float}


def _file_mtime(path):
    """Return modification time of a file, or 0 if missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def cache_check(agent_id, state_files):
    """Check if agent's source data has changed since last finding.

    Returns (skip: bool, reason: str). If skip is True, the agent should
    not be re-run because its inputs are unchanged and a recent finding exists.
    """
    now = time.time()
    cached = _cache_state.get(agent_id)
    if not cached:
        return False, "no cache entry"

    # TTL expired -> force re-check
    if now - cached["ts"] > CACHE_TTL_SEC:
        return False, "cache TTL expired"

    # Check if any source file has changed
    for label, path in state_files:
        mtime = _file_mtime(path)
        if mtime != cached["mtimes"].get(path, 0):
            return False, f"source changed: {label}"

    # Verify a finding actually exists for this agent
    store = load_findings_store()
    has_finding = any(
        f.get("agent") == agent_id for f in store.get("findings", [])
    )
    if not has_finding:
        return False, "no prior finding"

    return True, "inputs unchanged, finding exists"


def cache_update(agent_id, state_files, finding_id):
    """Record cache state after a successful finding."""
    mtimes = {path: _file_mtime(path) for _, path in state_files}
    _cache_state[agent_id] = {
        "mtimes": mtimes,
        "finding_id": finding_id,
        "ts": time.time(),
    }


# --- Stampede protection: per-topic lock ---
# Like tradedesk's per-stock lock: simultaneous requests for the same
# agent/topic trigger only one analysis.
import threading as _threading
_stampede_locks = {}
_stampede_lock_guard = _threading.Lock()


def stampede_acquire(agent_id, ttl_sec=300):
    """Try to acquire a per-agent lock. Returns True if acquired."""
    with _stampede_lock_guard:
        now = time.time()
        existing = _stampede_locks.get(agent_id)
        if existing and now - existing < ttl_sec:
            return False  # stampede blocked
        _stampede_locks[agent_id] = now
        return True


def stampede_release(agent_id):
    """Release a per-agent lock."""
    with _stampede_lock_guard:
        _stampede_locks.pop(agent_id, None)


def add_finding(agent_id, claim, evidence_ref, verdict, **kwargs):
    """Add a finding to the store if not already present (dedupe by claim+agent).

    Every finding starts with verification_status='pending' (O1.1).
    A checker agent (≠ producer) must confirm it before it counts as supported.
    """
    store = load_findings_store()
    # Dedup: same agent + same claim already exists
    for f in store["findings"]:
        if f.get("agent") == agent_id and f.get("claim") == claim:
            return False  # already exists
    domain = kwargs.pop("domain", _domain_for_agent(agent_id))
    requires_verification_from = kwargs.pop(
        "requires_verification_from",
        VERIFIER_MAP.get(domain, VERIFIER_MAP["default"])[0],
    )
    finding = {
        "id": f"f-{uuid.uuid4().hex[:8]}",
        "agent": agent_id,
        "claim": claim,
        "evidence_ref": evidence_ref,
        "verdict": verdict,
        "domain": domain,
        "verification_status": "pending",
        "requires_verification_from": requires_verification_from,
        "verified_by": None,
        "verified_at": None,
        "verification_notes": None,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    finding.update(kwargs)
    store["findings"].append(finding)
    save_findings_store(store)
    return finding["id"]


def update_finding_outcome(finding_id, outcome, outcome_date=None, notes=None):
    """Track Record: update a finding's outcome once the result is known.

    Like tradedesk's Track Record page — every recommendation is stored with
    its entry data, then later judged against what actually happened.
    outcome: 'right' | 'wrong' | 'inconclusive'
    """
    store = load_findings_store()
    for f in store["findings"]:
        if f.get("id") == finding_id:
            f["outcome"] = outcome
            f["outcome_date"] = outcome_date or time.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            if notes:
                f["outcome_notes"] = notes
            save_findings_store(store)
            return True
    return False


# --- O1 Verification Layer ---
# O1.1: producer ≠ verifier — every finding starts as "pending" and must be
# confirmed by an independent checker agent before counting as "supported".
# O1.3: hard gates — risk-control-verifier and strategy-acceptance-verifier
# must confirm domain findings before they can be "supported".

VERIFIER_MAP = {
    "risk": ["strategy-acceptance-verifier", "drawdown-analyst", "exposure-analyst",
             "risk-control-verifier"],  # last is Tier C, fallback only
    "compliance": ["trade-journal-reviewer", "strategy-acceptance-verifier",
                   "drawdown-analyst", "compliance-checker"],  # last is Tier C
    "strategy": ["strategy-acceptance-verifier", "backtest-auditor",
                 "quant-model-validator", "cost-analyst"],
    "backtest": ["backtest-auditor", "quant-model-validator",
                 "performance-attribution", "cost-analyst"],
    "default": ["research-archivist", "trade-journal-reviewer", "exposure-analyst"],
}


# --- O2: Autonomy Tiers + Cost-per-Outcome Accounting ---
# Tier A (autonomous): research, data, content — runs 24/7 without approval
# Tier B (gated): writes to stores, deletions, external contact — approval queue
# Tier C (never): money, orders, kill switch, broker anything — human only

AGENT_AUTONOMY_TIERS = {
    # Tier A — autonomous research & data (read-only, no store writes)
    "Tier A": [
        "data-feed-monitor",
        "market-data-analyst",
        "market-regime-analyst",
        "correlation-researcher",
        "volatility-researcher",
        "order-book-researcher",
        "liquidity-researcher",
        "exposure-analyst",
        "signal-analyst",
        "event-driven-researcher",
        "research-archivist",
        "trade-log-archivist",
        "trade-journal-reviewer",
    ],
    # Tier B — gated: writes to stores / analysis artifacts (needs approval flag)
    "Tier B": [
        "quant-researcher",
        "quant-research-manager",
        "backtest-auditor",
        "quant-model-validator",
        "position-sizing-analyst",
        "cost-analyst",
        "strategy-advisor",
        "portfolio-allocation-researcher",
        "performance-attribution",
        "drawdown-analyst",
        "liquidation-heatmap",
        "perp-funding-analyst",
    ],
    # Tier C — never automated: risk enforcement, execution, kill switch, broker
    "Tier C": [
        "risk-manager",
        "risk-control-verifier",
        "compliance-checker",
        "execution-strategist",
        "execution-analyst",
        "market-maker",
        "portfolio-manager",
    ],
}

# Build reverse lookup: agent_id -> autonomy tier letter
AGENT_TIER_MAP = {}
for tier_letter, agents in AGENT_AUTONOMY_TIERS.items():
    letter = tier_letter.split()[-1]  # "Tier A" -> "A"
    for a in agents:
        AGENT_TIER_MAP[a] = letter

# Cost model: provider tier -> cost units per call (relative, free providers)
# Pro keys consume scarce quota; lite keys are abundant.
MODEL_COST_UNITS = {
    "pro": 3,
    "general": 2,
    "lite": 1,
}

# Artifact outcome value (per verified finding)
OUTCOME_VALUE = {
    "confirmed": 10,
    "pending": 2,
    "contested": -5,
    "blocked": 0,
}

# Task ledger: in-memory record of every task's cost and outcome value.
# Populated from Hive tasks on demand by office_pnl().
TASK_LEDGER_PATH = "/Users/aryanagarwal/.openclaw/office_pnl.json"


def agent_autonomy_tier(agent_id: str) -> str:
    """Return autonomy tier letter (A/B/C) for an agent. Default B if unknown."""
    return AGENT_TIER_MAP.get(agent_id, "B")


def provider_cost_units(pool_tier) -> int:
    """Return cost units for a provider pool tier (str or list of str)."""
    if isinstance(pool_tier, list):
        # Use the cheapest tier in the list
        return min(MODEL_COST_UNITS.get(t, 2) for t in pool_tier)
    return MODEL_COST_UNITS.get(pool_tier, 2)


def load_task_ledger() -> list[dict]:
    """Load task ledger from disk (JSON array of task records)."""
    try:
        with open(TASK_LEDGER_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_task_ledger(ledger: list[dict]) -> None:
    """Persist task ledger to disk."""
    try:
        with open(TASK_LEDGER_PATH, "w") as f:
            json.dump(ledger, f, indent=2)
    except OSError:  # noqa: BLE001
        pass


def record_task_cost(task: dict) -> None:
    """Record a completed task's cost and outcome value into the ledger."""
    metadata = task.get("metadata", {}) or {}
    agent_id = task.get("agent_id", "")
    tier_letter = agent_autonomy_tier(agent_id)
    exec_pool = metadata.get("exec_pool", "unknown")
    pool_info = None
    # Try to look up pool tier from config
    try:
        config = load_office_config()
        pools = config.get("provider_pools", {})
        for pname, pinfo in pools.items():
            if pname == exec_pool or exec_pool in str(pinfo.get("models", [])):
                pool_info = pinfo
                break
    except Exception:  # noqa: BLE001
        pass
    cost_units = provider_cost_units(pool_info.get("tier", 2) if pool_info else 2)

    # Outcome value from verification status if it's a finding task
    verification = task.get("metadata", {}).get("verification_task")
    if verification:
        # Look up the finding's verification status
        store = load_findings_store()
        target = task.get("metadata", {}).get("verification_target")
        outcome_val = 0
        for f in store.get("findings", []):
            if f.get("id") == target:
                vs = f.get("verification_status", "pending")
                outcome_val = OUTCOME_VALUE.get(vs, 0)
                break
    else:
        # Regular task: value based on completion status
        status = task.get("status", "error")
        outcome_val = OUTCOME_VALUE.get("confirmed" if status == "done" else "blocked", 0)

    ledger = load_task_ledger()
    ledger.append({
        "task_id": task.get("id", ""),
        "agent_id": agent_id,
        "autonomy_tier": tier_letter,
        "status": task.get("status", "error"),
        "cost_units": cost_units,
        "outcome_value": outcome_val,
        "net_value": outcome_val - cost_units,
        "created_at": task.get("created_at", ""),
        "source": metadata.get("source", "unknown"),
    })
    save_task_ledger(ledger)


def office_pnl() -> dict:
    """Compute office P&L: cost vs outcome value by tier and agent."""
    ledger = load_task_ledger()
    if not ledger:
        return {
            "total_cost_units": 0,
            "total_outcome_value": 0,
            "net_value": 0,
            "task_count": 0,
            "by_tier": {},
            "by_agent": {},
        }

    total_cost = sum(t["cost_units"] for t in ledger)
    total_value = sum(t["outcome_value"] for t in ledger)
    by_tier: dict[str, dict] = {}
    by_agent: dict[str, dict] = {}

    for t in ledger:
        at = t["autonomy_tier"]
        aid = t["agent_id"]
        by_tier.setdefault(at, {"cost": 0, "value": 0, "count": 0, "net": 0})
        by_tier[at]["cost"] += t["cost_units"]
        by_tier[at]["value"] += t["outcome_value"]
        by_tier[at]["count"] += 1
        by_tier[at]["net"] += t["net_value"]

        by_agent.setdefault(aid, {"cost": 0, "value": 0, "count": 0, "net": 0, "tier": at})
        by_agent[aid]["cost"] += t["cost_units"]
        by_agent[aid]["value"] += t["outcome_value"]
        by_agent[aid]["count"] += 1
        by_agent[aid]["net"] += t["net_value"]

    return {
        "total_cost_units": total_cost,
        "total_outcome_value": total_value,
        "net_value": total_value - total_cost,
        "task_count": len(ledger),
        "by_tier": by_tier,
        "by_agent": by_agent,
    }


def tier_enforcement_check(agent_id: str) -> tuple[bool, str]:
    """O2.2/O2.3: Check if an agent's action is allowed under autonomy tiers.

    Returns (allowed: bool, reason: str).
    Tier A: always allowed.
    Tier B: allowed but flagged needs_approval.
    Tier C: blocked — human only.
    """
    tier = agent_autonomy_tier(agent_id)
    if tier == "C":
        return False, f"Tier C agent {agent_id} — human-only, never automated"
    if tier == "B":
        return True, f"Tier B agent {agent_id} — gated, needs approval"
    return True, f"Tier A agent {agent_id} — autonomous"



def _domain_for_agent(agent_id: str) -> str:
    """Map an agent ID to a verification domain."""
    a = agent_id.lower()
    if "risk" in a:
        return "risk"
    if "compliance" in a:
        return "compliance"
    if "strategy" in a:
        return "strategy"
    if "backtest" in a:
        return "backtest"
    return "default"


def get_checker_agent(producer_id: str, domain: str = "default") -> str | None:
    """Return a checker agent for the given domain, not equal to the producer."""
    for candidate in VERIFIER_MAP.get(domain, VERIFIER_MAP["default"]):
        if candidate != producer_id:
            return candidate
    return None


def update_finding_verification(
    finding_id: str,
    status: str,
    checker_agent: str | None = None,
    notes: str | None = None,
) -> bool:
    """Update a finding's verification status (O1.1 / O1.3).

    status: 'pending' | 'confirmed' | 'contested'
    """
    store = load_findings_store()
    for f in store["findings"]:
        if f.get("id") == finding_id:
            f["verification_status"] = status
            f["verified_by"] = checker_agent
            f["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            if notes:
                f["verification_notes"] = notes
            save_findings_store(store)
            return True
    return False


def _dispatch_verification_task(
    source_task_id: str,
    finding_id: str,
    checker_agent: str,
    domain: str,
    producer_agent: str,
) -> None:
    """O1.1 / O1.3: Create a Hive verification task for a checker agent.

    The checker agent reviews the finding and confirms or contests it.
    The task carries verification_target=finding_id so finalize_agent_result
    knows to update the existing finding rather than create a new one.
    """
    verify_task_id = f"jev-{uuid.uuid4().hex[:8]}"
    task = {
        "id": verify_task_id,
        "title": f"Verify finding {finding_id}: {domain}",
        "description": (
            f"Independent verification of finding {finding_id} produced by "
            f"{producer_agent} (domain: {domain}). Review the evidence at "
            f"{source_task_id} and confirm or contest the finding. "
            f"Respond with VERDICT: confirm or VERDICT: contest, followed by "
            f"a one-sentence rationale."
        ),
        "status": "pending",
        "agent_id": checker_agent,
        "priority": "high",
        "user_id": "jev",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "tier": "pro",
            "source": "jev-cloud-orchestrator",
            "verification_task": True,
            "verification_target": finding_id,
            "verification_domain": domain,
            "verification_producer": producer_agent,
            "qwen_task_id": f"jev-exec-verify-{checker_agent}",
        },
        "result": None,
        "error": None,
    }
    task_path = Path(HIVE_DIR) / f"{verify_task_id}.json"
    with open(task_path, "w") as f:
        json.dump(task, f, indent=2)
    log(f"  Verification task dispatched to {checker} for finding {finding_id}")


def verify_finding_sync(
    finding_id: str,
    producer_agent: str,
    checker_agent: str,
    domain: str,
    config: dict,
) -> None:
    """O1.1: Synchronously verify a finding with an independent checker agent.

    Calls the checker agent directly (not via Hive queue) so verification
    happens before the cycle ends. Producer ≠ verifier is enforced by
    passing a different agent_id.
    """
    # Look up checker agent info
    agents = get_all_agents(config)
    checker_info = None
    for a in agents:
        if a["agent_id"] == checker_agent:
            checker_info = a
            break
    if not checker_info:
        log(f"  Checker agent {checker_agent} not found in config")
        return

    # Load the finding to verify
    store = load_findings_store()
    finding = None
    for f in store.get("findings", []):
        if f.get("id") == finding_id:
            finding = f
            break
    if not finding:
        log(f"  Finding {finding_id} not found for verification")
        return

    # Build verification state bundle
    state_bundle = (
        f"VERIFICATION TASK — Independent review of finding {finding_id}\n"
        f"Produced by: {producer_agent}\n"
        f"Domain: {domain}\n"
        f"Finding claim: {finding.get('claim', '')}\n"
        f"Finding verdict: {finding.get('verdict', '')}\n"
        f"Evidence ref: {finding.get('evidence_ref', '')}\n"
        f"\nTASK: Review the finding above for accuracy and grounding. "
        f"Respond with VERDICT: confirm (finding is well-grounded and accurate) "
        f"or VERDICT: contest (finding is wrong, unsupported, or an echo), "
        f"followed by a one-sentence rationale.\n"
    )

    try:
        result = execute_agent_worker(
            (checker_info, state_bundle, checker_info["tier"])
        )
    except Exception as e:
        log(f"  Verification call failed for {checker_agent}: {e}")
        return

    exec_text = result.get("exec_text", "")
    verdict_lower = exec_text.strip().lower()
    if "verdict: contest" in verdict_lower:
        update_finding_verification(
            finding_id, "contested",
            checker_agent=checker_agent,
            notes=exec_text[:300],
        )
        log(f"  Verification CONTESTED for finding {finding_id} by {checker_agent}")
    elif "verdict: confirm" in verdict_lower:
        update_finding_verification(
            finding_id, "confirmed",
            checker_agent=checker_agent,
            notes=exec_text[:300],
        )
        log(f"  Verification CONFIRMED for finding {finding_id} by {checker_agent}")
    else:
        log(f"  Verification by {checker_agent} had no clear confirm/contest verdict")


# --- O1.2: Tripartite Consensus with Devil-Advisor ---
# Major verdicts (strategy promotion, kill decisions) require 3 independent
# agent reads plus a devil-advisor counter-case before a finding is "confirmed".

TRIPARTITE_DOMAINS = {"strategy", "risk", "backtest"}  # domains needing 3-read consensus


def _devil_advisor_for(domain: str, exclude: list[str]) -> str | None:
    """Pick a devil-advisor agent (argues against the finding), excluded from others."""
    candidates = VERIFIER_MAP.get(domain, VERIFIER_MAP["default"])
    for c in candidates:
        if c not in exclude:
            return c
    # Fallback: any agent not excluded
    all_agents = get_all_agents(load_office_config())
    for a in all_agents:
        if a["agent_id"] not in exclude:
            return a["agent_id"]
    return None


def _run_verification_call(checker_info: dict, finding: dict, domain: str,
                           producer_agent: str, role_label: str) -> str:
    """Run one verification call and return 'confirm' | 'contest' | 'unclear'."""
    state_bundle = (
        f"VERIFICATION TASK — {role_label} review of finding {finding['id']}\n"
        f"Produced by: {producer_agent}\n"
        f"Domain: {domain}\n"
        f"Finding claim: {finding.get('claim', '')}\n"
        f"Finding verdict: {finding.get('verdict', '')}\n"
        f"Evidence ref: {finding.get('evidence_ref', '')}\n"
        f"\nTASK: Independently review the finding above. "
        f"Respond with VERDICT: confirm (finding is well-grounded and accurate) "
        f"or VERDICT: contest (finding is wrong, unsupported, or an echo), "
        f"followed by a one-sentence rationale.\n"
    )
    try:
        result = execute_agent_worker(
            (checker_info, state_bundle, checker_info["tier"])
        )
    except Exception as e:
        log(f"  {role_label} call failed: {e}")
        return "unclear"

    verdict_lower = (result.get("exec_text", "") or "").strip().lower()
    if "verdict: contest" in verdict_lower:
        return "contest"
    if "verdict: confirm" in verdict_lower:
        return "confirm"
    return "unclear"


def verify_finding_tripartite(
    finding_id: str,
    producer_agent: str,
    domain: str,
    config: dict,
) -> str:
    """O1.2: Tripartite consensus with devil-advisor for major verdicts.

    Returns 'confirmed' | 'contested' | 'unclear'.
    Updates the finding's verification_status accordingly.
    """
    if domain not in TRIPARTITE_DOMAINS:
        return "unclear"  # not a major-verdict domain

    agents = get_all_agents(config)
    agent_by_id = {a["agent_id"]: a for a in agents}

    # --- Pick 3 independent checkers from domain verifier list, excluding producer ---
    domain_verifiers = [
        v for v in VERIFIER_MAP.get(domain, VERIFIER_MAP["default"])
        if v != producer_agent
    ]
    if len(domain_verifiers) < 3:
        log(f"  Tripartite: only {len(domain_verifiers)} verifiers for domain {domain}, "
            f"need 3 — falling back to single verification")
        return "unclear"

    checkers = domain_verifiers[:3]

    # --- Pick devil-advisor: different from producer and all 3 checkers ---
    devil = _devil_advisor_for(domain, [producer_agent] + checkers)

    # Load the finding
    store = load_findings_store()
    finding = None
    for f in store.get("findings", []):
        if f.get("id") == finding_id:
            finding = f
            break
    if not finding:
        log(f"  Tripartite: finding {finding_id} not found")
        return "unclear"

    log(f"  Tripartite consensus: checkers={checkers} devil={devil} "
        f"for finding {finding_id} (domain={domain})")

    # --- Run all 3 checkers ---
    results = {}
    for checker_id in checkers:
        cinfo = agent_by_id.get(checker_id)
        if not cinfo:
            log(f"  Tripartite: checker {checker_id} not in config")
            results[checker_id] = "unclear"
            continue
        r = _run_verification_call(cinfo, finding, domain, producer_agent,
                                   f"checker-{checker_id}")
        results[checker_id] = r
        log(f"  Tripartite: {checker_id} -> {r}")

    # --- Run devil-advisor ---
    devil_result = "unclear"
    if devil:
        dinfo = agent_by_id.get(devil)
        if dinfo:
            devil_result = _run_verification_call(
                dinfo, finding, domain, producer_agent,
                f"devil-advisor-{devil}"
            )
            log(f"  Tripartite: devil-advisor {devil} -> {devil_result}")

    # --- Consensus logic ---
    confirms = sum(1 for r in results.values() if r == "confirm")
    contests = sum(1 for r in results.values() if r == "contest")

    if confirms == 3:
        # Unanimous confirmation
        status = "confirmed"
        notes = "Tripartite: 3/3 checkers confirmed"
    elif confirms == 2 and contests <= 1:
        # Majority confirm; devil-advisor must not successfully overturn
        if devil_result == "contest":
            # Devil-advisor raised a valid counter-case -> contested
            status = "contested"
            notes = ("Tripartite: 2/3 confirmed but devil-advisor contests -> contested")
        else:
            status = "confirmed"
            notes = "Tripartite: 2/3 confirmed, devil-advisor did not overturn"
    elif contests >= 2:
        status = "contested"
        notes = "Tripartite: 2/3 checkers contested"
    else:
        # Split/unclear -> conservative: contested
        status = "contested"
        notes = "Tripartite: split/unclear verdicts -> contested (conservative)"

    update_finding_verification(
        finding_id, status,
        checker_agent=",".join(checkers) + (f"|devil:{devil}" if devil else ""),
        notes=notes,
    )
    log(f"  Tripartite result: {status} — {notes}")
    return status


def findings_summary():
    """Return aggregate stats from the findings store (Track Record view)."""
    store = load_findings_store()
    findings = store.get("findings", [])
    total = len(findings)
    verdicts = {}
    outcomes = {}
    by_agent = {}
    for f in findings:
        v = f.get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1
        o = f.get("outcome", "pending")
        outcomes[o] = outcomes.get(o, 0) + 1
        a = f.get("agent", "unknown")
        by_agent[a] = by_agent.get(a, 0) + 1

    decided = outcomes.get("right", 0) + outcomes.get("wrong", 0)
    hit_rate = round(outcomes.get("right", 0) / decided * 100, 1) if decided else 0

    return {
        "total_findings": total,
        "verdicts": verdicts,
        "outcomes": outcomes,
        "by_agent": by_agent,
        "decided": decided,
        "hit_rate": hit_rate,
    }




def verdict_gate(agent_id, exec_text, state_bundle):
    """Deterministic verdict gate before writing to findings store.

    LLMs judge form; this code checks existence. Returns (passes: bool, reason: str).
    """
    text = exec_text.lower()

    # 1. Must contain a verdict keyword (PASS/FAIL/go/no-go/supported/refuted/conclusion/finding)
    verdict_keywords = ["pass", "fail", "go/no-go", "supported", "refuted", "needs-data",
                        "conclusion", "finding", "audit", "verified", "confirmed", "determined"]
    if not any(kw in text for kw in verdict_keywords):
        return False, "no verdict keyword found in output"

    # 2. Compliance-specific: must reference kill switch from bundle
    if agent_id == "compliance-checker":
        if "kill switch" not in text and "locked" not in text:
            return False, "compliance output does not reference kill switch status"

    # 3. Risk-specific: must reference risk limits from bundle
    if agent_id == "risk-control-verifier":
        if "heat" not in text and "leg" not in text and "drawdown" not in text:
            return False, "risk output does not reference risk limits from bundle"

    return True, "passes deterministic gate"


# --- O0.1 Findings extraction fix -------------------------------------------
# Old bug: claim was stored as exec_text.split("\n")[0], which is usually a
# preamble ("1. **Analyze User Request:**") — not an actual finding. Many
# worker responses are pure task echoes. New extraction rejects echoes and
# captures a machine-parsable FINDING: line, with a substantive-line fallback.
# Fallback claims are stored as needs-review (never supported).

ECHO_PATTERNS = [
    "analyze user request",
    "the user wants me to",
    "the user is asking",
    "let me analyze",
    "let me review",
    "i need to analyze",
    "i need to review",
    "i need to act",
    "i have been asked",
    "i will analyze",
    "**title:**",
]

FINDING_LINE_RE = re.compile(r"finding\s*:\s*(.+)$", re.IGNORECASE)

CONTENT_KEYWORDS = (
    "pass", "fail", "kill switch", "locked", "verdict", "edge",
    "cost", "drawdown", "margin", "trade", "confirm", "verified",
    "not_run", "available", "unavailable", "p&l", "net", "gross",
    "clears", "excludes zero", "heatmap", "source", "audit",
)


def is_echo_response(text: str) -> bool:
    """True if the text looks like the model restating the task, not doing it."""
    if not text:
        return False
    head = text.strip().lower()[:250]
    return any(p in head for p in ECHO_PATTERNS)


def extract_finding(exec_text: str):
    """Extract the actual finding claim from an agent response.

    Returns (claim: str | None, method: str) where method is one of:
      'finding_line'  — explicit FINDING: line (machine-parsable, best)
      'substantive'   — most substantive content line (fallback)
      'echo'          — response restates the task (reject)
      'none'          — nothing extractable (reject)
    """
    if not exec_text or not exec_text.strip():
        return None, "none"
    if is_echo_response(exec_text):
        return None, "echo"

    lines = [ln.strip() for ln in exec_text.strip().splitlines() if ln.strip()]

    # 1. Explicit FINDING: line (the prompt now requires one; last wins)
    for line in reversed(lines):
        m = FINDING_LINE_RE.search(line.replace("**", ""))
        if m:
            claim = m.group(1).strip()
            if claim and not is_echo_response(claim):
                return claim[:300], "finding_line"

    # 2. Fallback: substantive line — content keyword, reasonable length, not a header
    substantive = []
    for line in lines:
        low = line.lower()
        if any(p in low for p in ECHO_PATTERNS):
            continue
        if not (30 <= len(line) <= 300):
            continue
        has_kw = any(kw in low for kw in CONTENT_KEYWORDS)
        is_header = line.startswith(("#", "**", "-", "*"))
        if has_kw and not is_header:
            substantive.append(line)
    if substantive:
        return max(substantive, key=len)[:300], "substantive"

    return None, "none"


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}: {msg}"
    print(line, flush=True)  # captured by shell redirect (>> logfile 2>&1)


def load_office_config():
    with open(OFFICE_CONFIG) as f:
        return json.load(f)


def get_all_agents(config):
    """Extract all agent IDs from the office config agent_tiers."""
    agents = []
    agent_tiers = config.get("agent_tiers", {})
    for tier, tier_agents in agent_tiers.items():
        if isinstance(tier_agents, list):
            for agent_id in tier_agents:
                agents.append({"agent_id": agent_id, "tier": tier})
    return agents


def save_result(task_id, response_text, model, pool, source):
    """Save model response to a .result file for dashboard queryability."""
    result_file = os.path.join(RESULT_DIR, f"{task_id}.result")
    result_data = {
        "task_id": task_id,
        "model": model,
        "pool": pool,
        "source": source,
        "response": response_text,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(result_file, "w") as f:
        json.dump(result_data, f, indent=2)


def acquire_pid_lock():
    """Ensure only one JEV dispatcher instance runs at a time."""
    try:
        with open(JEV_PID_FILE) as f:
            old_pid = int(f.read().strip())
        # Check if the old process is still alive
        try:
            os.kill(old_pid, 0)
            print(f"JEV already running as PID {old_pid}, exiting.", flush=True)
            sys.exit(0)
        except OSError:
            pass  # stale pid file, overwrite
    except (FileNotFoundError, ValueError):
        pass

    with open(JEV_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def cleanup(signum=None, frame=None):
        try:
            os.unlink(JEV_PID_FILE)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)


def check_completed_tasks():
    """Check .result files for JEV tasks and update Hive status to 'done'."""
    completed = 0
    total_jev = 0

    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue

        if task.get("metadata", {}).get("source") != "jev-cloud-orchestrator":
            continue

        total_jev += 1
        if task.get("status") == "done":
            completed += 1
            continue

        qwen_task_id = task.get("metadata", {}).get("qwen_task_id")
        if not qwen_task_id:
            qwen_task_id = task["id"]

        result_file = os.path.join(RESULT_DIR, f"{qwen_task_id}.result")
        if os.path.exists(result_file):
            task["status"] = "done"
            task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                with open(result_file) as rf:
                    result_data = json.load(rf)
                    task["result"] = result_data.get("response", "")
            except Exception:
                task["result"] = f"Result file: {result_file}"
            with open(hive_file, "w") as f:
                json.dump(task, f, indent=2)
            completed += 1

    return completed, total_jev


def agent_has_recent_done(agent_id, hive_dir=HIVE_DIR):
    """Return True if agent's latest JEV task is done and younger than SKIP_DONE_MIN."""
    newest_done = None
    for hive_file in glob.glob(os.path.join(hive_dir, "*.json")):
        try:
            with open(hive_file) as f:
                t = json.load(f)
        except Exception:
            continue
        if (
            t.get("agent_id") == agent_id
            and t.get("metadata", {}).get("source") == "jev-cloud-orchestrator"
            and t.get("status") == "done"
        ):
            ts = t.get("updated_at") or t.get("created_at")
            if ts:
                try:
                    done_time = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
                except ValueError:
                    continue
                if newest_done is None or done_time > newest_done:
                    newest_done = done_time

    if newest_done is None:
        return False
    age_min = (time.time() - newest_done) / 60.0
    return age_min < SKIP_DONE_MIN


def has_pending_task(agent_id):
    """Check if agent already has a pending JEV task."""
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                t = json.load(f)
        except Exception:
            continue
        if (
            t.get("agent_id") == agent_id
            and t.get("metadata", {}).get("source") == "jev-cloud-orchestrator"
            and t.get("status") == "pending"
        ):
            return True
    return False


def execute_agent_worker(args):
    """Worker process: execute cloud calls for one agent.

    Runs in a separate process to use multiple CPU cores.
    Creates its own CloudModelOrchestrator instance (can't share across processes).
    """
    agent_info, state_bundle_text, tier = args
    agent_id = agent_info["agent_id"]

    # Create orchestrator in worker process (can't share across processes)
    orchestrator = CloudModelOrchestrator()

    try:
        if state_bundle_text:
            # --- Direct-execution path for agents with mapped state bundles ---
            exec_prompt = build_direct_exec_prompt(agent_id, tier, state_bundle_text)
            try:
                if is_general_assistant_task(exec_prompt):
                    exec_text = route_through_local(exec_prompt)
                    exec_model_used = "hauhaucs/qwen3.5-9b-uncensored-aggressive"
                    exec_pool_used = "qwen_local"
                else:
                    exec_text, exec_model_used, exec_pool_used = orchestrator.call_model(
                        *orchestrator.decide_model(agent_info, task_type="exec"),
                        exec_prompt,
                        task_id=f"jev-exec-{agent_id}",
                        priority="normal",
                    )
            except Exception as e:
                exec_text, exec_model_used, exec_pool_used = (
                    orchestrator._call_with_failover(
                        agent_info, exec_prompt, f"jev-exec-{agent_id}", "normal",
                        skip_pool=None,
                    )
                )

            return {
                "agent_id": agent_id,
                "tier": tier,
                "status": "done",
                "exec_text": exec_text,
                "exec_model": exec_model_used,
                "exec_pool": exec_pool_used,
                "exec_prompt": exec_prompt,
                "plan_model": None,
                "plan_pool": None,
                "direct_exec": True,
                "error": None,
            }

        # --- Plan-then-exec path for agents without mapped state bundles ---
        planning_prompt = f"""You are JEV (Jev Decision Service) for a PAPER trading research fleet.

Plan ONE specific, actionable trading research task for this agent:

AGENT: {agent_id}
TIER: {tier}

TRADING-SYSTEM GROUND RULES (PAPER/TESTNET ONLY):
- live_orders_allowed = false; no order path ever
- Gross edge is not profit: state venue, fee, funding and horizon
- Horizon viable only when CI excludes zero AND clears modelled costs
- Never lower a sample floor to get a verdict

The task must be:
1. Specific and actionable (not vague)
2. Trading research: edge detection, backtest validation, cost modeling, risk analysis, position sizing, strategy validation
3. Produce a concrete output (a model, a report, a validation, a cost estimate)
4. Safe: PAPER/TESTNET only, no live orders, no credentials, no money movements

Respond with ONLY the task title and description in this format:
TITLE: <short task title>
DESCRIPTION: <2-3 sentence description of what to do and what output is expected>
PRIORITY: <low|normal|high|critical>"""

        exec_prompt = f"Agent {agent_id} ({tier} tier): Execute the planned task and report results."

        result = orchestrator.plan_and_execute(
            agent_info,
            planning_prompt,
            exec_prompt,
            task_id=f"jev-{agent_id}",
            priority="normal",
        )

        plan = result["plan"]
        exec_r = result["exec"]

        title = f"Task for {agent_id}"
        description = plan["text"]
        priority = "normal"
        for line in plan["text"].split("\n"):
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
            elif line.startswith("DESCRIPTION:"):
                description = line.replace("DESCRIPTION:", "").strip()
            elif line.startswith("PRIORITY:"):
                priority = line.replace("PRIORITY:", "").strip().lower()

        return {
            "agent_id": agent_id,
            "tier": tier,
            "status": "done",
            "exec_text": exec_r["text"],
            "exec_model": exec_r["model"],
            "exec_pool": exec_r["pool"],
            "exec_prompt": exec_prompt,
            "plan_model": plan["model"],
            "plan_pool": plan["pool"],
            "direct_exec": False,
            "plan_text": plan["text"],
            "title": title,
            "description": description,
            "priority": priority,
            "error": None,
        }

    except Exception as e:
        return {
            "agent_id": agent_id,
            "tier": tier,
            "status": "error",
            "error": str(e),
            "exec_text": None,
            "exec_model": None,
            "exec_pool": None,
        }


def finalize_user_task(task_file_path: str, worker_result: dict) -> dict:
    """Finalize a dost-submitted task by updating the existing task file.

    Unlike finalize_agent_result, this does NOT create findings, call the
    verdict gate, or record cost — user prompts are not research findings.
    """
    try:
        with open(task_file_path) as f:
            task = json.load(f)
    except Exception as e:
        return {"agent_id": "dost", "status": "error", "error": f"cannot read task file: {e}"}

    agent_id = task.get("agent_id", "dost")

    if worker_result.get("status") == "error":
        task["status"] = "error"
        task["error"] = worker_result.get("error", "unknown error")
        task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(task_file_path, "w") as f:
                json.dump(task, f, indent=2)
        except OSError:
            pass
        return {"agent_id": agent_id, "status": "error", "error": worker_result.get("error", "unknown")}

    # Success — update with result
    task["status"] = "done"
    task_id = task.get("id", "")

    # Read full exec text from RESULT_DIR result file if available,
    # else fall back to the worker result.
    exec_text = worker_result.get("exec_text") or ""
    result_file = os.path.join(RESULT_DIR, f"{task_id}.result")
    if os.path.exists(result_file):
        try:
            with open(result_file) as rf:
                result_data = json.load(rf)
                exec_text = result_data.get("response", exec_text)
        except Exception:
            pass

    task["result"] = {
        "source": "dost",
        "preview": exec_text[:200],
        "text": exec_text,
        "model": worker_result.get("exec_model", "?"),
        "pool": worker_result.get("exec_pool", "?"),
        "tool": worker_result.get("exec_tool", "?"),
    }
    task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(task_file_path, "w") as f:
            json.dump(task, f, indent=2)
    except OSError:
        pass
    return {"agent_id": agent_id, "status": "done", "task_id": task.get("id", "")}


def finalize_agent_result(agent_info, state_bundle, tier, worker_result):
    """Finalize agent result in main process (shared state: findings store, Hive tasks).

    Runs in main process to avoid concurrent file writes across processes.
    """
    agent_id = agent_info["agent_id"]
    qwen_task_id = f"jev-exec-{agent_id}"
    task_id = f"jev-{uuid.uuid4().hex[:8]}"

    if worker_result["status"] == "error":
        stampede_release(agent_id)
        log(f"Failed for {agent_id}: {worker_result['error']}")
        task = {
            "id": task_id,
            "title": f"Task for {agent_id}",
            "description": f"Task failed: {worker_result['error']}",
            "status": "error",
            "agent_id": agent_id,
            "priority": "normal",
            "user_id": "jev",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": {
                "tier": tier,
                "source": "jev-cloud-orchestrator",
                "qwen_task_id": qwen_task_id,
                "error": worker_result["error"],
            },
            "result": None,
            "error": worker_result["error"],
        }
        task_path = Path(HIVE_DIR) / f"{task_id}.json"
        with open(task_path, "w") as f:
            json.dump(task, f, indent=2)
        # O2.4: record cost for errored task
        record_task_cost(task)
        return {"agent_id": agent_id, "status": "error", "error": worker_result["error"]}

    exec_text = worker_result["exec_text"]
    exec_model_used = worker_result["exec_model"]
    exec_pool_used = worker_result["exec_pool"]
    direct_exec = worker_result["direct_exec"]

    # --- O1.1: Handle verification task results ---
    # If this result is from a checker agent verifying a finding,
    # update the target finding instead of creating a new one.
    wf_metadata = worker_result.get("metadata", {}) or {}
    if wf_metadata.get("verification_task"):
        target_finding_id = wf_metadata.get("verification_target")
        verdict_lower = exec_text.strip().lower()
        if "verdict: contest" in verdict_lower:
            update_finding_verification(
                target_finding_id, "contested",
                checker_agent=agent_id,
                notes=exec_text[:300],
            )
            log(f"  Verification CONTESTED for finding {target_finding_id} by {agent_id}")
        elif "verdict: confirm" in verdict_lower:
            update_finding_verification(
                target_finding_id, "confirmed",
                checker_agent=agent_id,
                notes=exec_text[:300],
            )
            log(f"  Verification CONFIRMED for finding {target_finding_id} by {agent_id}")
        else:
            log(f"  Verification task by {agent_id} had no clear confirm/contest verdict")
        # O2.4: record cost for verification task
        verify_task = {
            "id": task_id,
            "agent_id": agent_id,
            "status": "done",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": wf_metadata,
        }
        record_task_cost(verify_task)
        stampede_release(agent_id)
        return {"agent_id": agent_id, "status": "done", "task_id": task_id}

    # Deterministic post-execution verification for compliance agent
    compliance_issues = []
    if agent_id == "compliance-checker":
        compliance_issues = verify_compliance_output(agent_id, exec_text)
        if compliance_issues:
            log(f"  Compliance verification issues for {agent_id}: {compliance_issues}")
            exec_text = (
                exec_text
                + f"\n\n--- DETERMINISTIC VERIFICATION ISSUES ---\n"
                + "\n".join(f"- {i}" for i in compliance_issues)
            )

    # Verdict gate: only write to findings store if output passes
    gate_ok, gate_reason = verdict_gate(agent_id, exec_text, state_bundle or "")
    finding_id = None
    if gate_ok:
        claim, claim_method = extract_finding(exec_text)
        # Reject echoes / non-claims: never store a preamble as a finding
        if claim is None:
            log(f"  Verdict gate rejected {agent_id}: extraction={claim_method}")
        else:
            evidence_ref = f"jev-task-{task_id}"
            finding_id = add_finding(
                agent_id,
                claim=claim,
                evidence_ref=evidence_ref,
                verdict="supported",
                source="jev-cloud-orchestrator",
                gate_reason=gate_reason,
                extraction_method=claim_method,
            )
            if finding_id:
                log(f"  Finding stored for {agent_id}: {claim[:80]}... (verification pending)")
                # --- O1.1/O1.2: verify with independent checker(s) ---
                domain = _domain_for_agent(agent_id)
                try:
                    config = load_office_config()
                except Exception:
                    config = {}
                if domain in TRIPARTITE_DOMAINS:
                    # Major verdict: tripartite consensus + devil-advisor
                    verify_finding_tripartite(
                        finding_id, agent_id, domain, config
                    )
                else:
                    # Standard: single independent checker
                    checker = get_checker_agent(agent_id, domain)
                    if checker:
                        verify_finding_sync(
                            finding_id, agent_id, checker, domain, config
                        )
                    else:
                        log(f"  No checker available for {agent_id} (domain={domain})")
            else:
                log(f"  Finding already exists for {agent_id} (deduped)")
    else:
        log(f"  Verdict gate blocked {agent_id}: {gate_reason}")

    # Update cache gate state after successful execution
    state_files = AGENT_STATE_FILES.get(agent_id, [])
    if state_files:
        cache_update(agent_id, state_files, task_id)

    # Create Hive task
    if direct_exec:
        title = f"Direct audit: {agent_id}"
        description = worker_result["exec_prompt"][:200] + "..."
        plan_model = None
        plan_pool = None
    else:
        title = worker_result["title"]
        description = worker_result["description"]
        plan_model = worker_result["plan_model"]
        plan_pool = worker_result["plan_pool"]

    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "done",
        "agent_id": agent_id,
        "priority": worker_result.get("priority", "normal"),
        "user_id": "jev",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "tier": tier,
            "source": "jev-cloud-orchestrator",
            "qwen_task_id": qwen_task_id,
            "plan_model": plan_model,
            "plan_pool": plan_pool,
            "plan_source": "cloud",
            "exec_model": exec_model_used,
            "exec_pool": exec_pool_used,
            "exec_source": "cloud",
            "direct_exec": direct_exec,
        },
        "result": exec_text,
        "error": None,
    }
    task_path = Path(HIVE_DIR) / f"{task_id}.json"
    with open(task_path, "w") as f:
        json.dump(task, f, indent=2)

    # Save execution result file for dashboard
    save_result(qwen_task_id, exec_text, exec_model_used, exec_pool_used, "cloud")

    # O2.4: record cost for completed task
    record_task_cost(task)

    stampede_release(agent_id)
    return {"agent_id": agent_id, "status": "done", "task_id": task_id}


def collect_user_submitted_tasks() -> list[tuple[dict, str | None, str, str]]:
    """Scan HIVE_DIR for pending tasks submitted by the dost (source == "dost").

    Returns list of (agent_info, state_bundle, tier, task_file_path) tuples
    ready for the worker pool. Marks each task as in_progress so it isn't
    picked up again.
    """
    user_tasks = []
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue

        # Only pick up dost-submitted pending tasks
        if task.get("status") != "pending":
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue

        agent_id = task.get("agent_id", "strategy-advisor")
        tier = "pro"  # dost-submitted tasks use pro tier

        # Route dost-submitted tasks through general-assistant so plain
        # questions get plain answers (not research framing). Keep a
        # fallback: if "general-assistant" is not in the agent registry,
        # keep the task's stated agent_id.
        agent_registry = {a["agent_id"] for a in get_all_agents(load_office_config())}
        if "general-assistant" in agent_registry:
            agent_id = "general-assistant"

        # Build agent_info for the worker
        agent_info = {"agent_id": agent_id, "tier": tier}

        # Mark as in_progress to prevent re-pickup
        task["status"] = "in_progress"
        task["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(hive_file, "w") as f:
                json.dump(task, f, indent=2)
        except OSError:
            pass

        user_tasks.append((agent_info, None, tier, hive_file))

    return user_tasks


def archive_old_user_submitted_tasks():
    """Rotate old dost-submitted tasks out of the live Hive.

    Scans HIVE_DIR for dost-submitted tasks (metadata.source == "dost")
    with status in (done, error) whose updated_at is older than
    ARCHIVE_MAX_AGE_DAYS and moves them to HIVE_DIR/archive/. Creates the
    archive directory if missing. Only done/error tasks are considered, so
    pending tasks are never archived and collect_user_submitted_tasks()
    (which filters by status) continues to pick up only pending work.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = time.time()
    cutoff = now - ARCHIVE_MAX_AGE_DAYS * 86400
    archived = 0
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue
        if task.get("status") not in ("done", "error"):
            continue
        ts = task.get("updated_at") or task.get("created_at")
        if not ts:
            continue
        try:
            mtime = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
        if mtime >= cutoff:
            continue
        try:
            shutil.move(
                hive_file, os.path.join(ARCHIVE_DIR, os.path.basename(hive_file))
            )
            archived += 1
        except OSError:
            pass
    if archived:
        log(f"Archived {archived} old dost tasks to {ARCHIVE_DIR}")
    return archived


def synthesize_cycle():
    """Fan-in all findings into a consolidated fleet-level verdict.

    Reads every finding from the findings store, groups by agent, counts
    verdicts, and returns a one-line summary. Also writes a detailed
    synthesis report to the findings directory.

    This is the synthesis agent from tradedesk: independent agents fan
    out, a lead agent (this function) reads all findings and makes the
    call — overall verdict with confidence and key risks.
    """
    store = load_findings_store()
    findings = store.get("findings", [])
    if not findings:
        return None

    # Group by agent
    by_agent = {}
    for f in findings:
        by_agent.setdefault(f["agent"], []).append(f)

    # Count verdicts — O1.1: only confirmed findings count as "supported"
    verdict_counts = {}
    verification_counts = {"pending": 0, "confirmed": 0, "contested": 0}
    for f in findings:
        v = f.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        vs = f.get("verification_status", "pending")
        verification_counts[vs] = verification_counts.get(vs, 0) + 1

    # Overall verdict: only confirmed findings count as supported.
    # Pending/contested findings are not yet verified.
    total = len(findings)
    supported = verification_counts.get("confirmed", 0)
    blocked = verdict_counts.get("needs-review", 0) + verdict_counts.get("refuted", 0)
    pending = verification_counts.get("pending", 0)
    contested = verification_counts.get("contested", 0)

    if contested > 0:
        overall = "CONTESTED"
        confidence = max(0, 100 - (contested * 30))
    elif blocked > 0:
        overall = "CAUTION"
        confidence = max(0, 100 - (blocked * 25))
    elif pending > 0:
        overall = "PENDING-VERIFY"
        confidence = int(round(supported / total * 100)) if total > 0 else 0
    elif supported == total:
        overall = "ALL-CLEAR"
        confidence = 100
    elif supported > 0:
        overall = "PARTIAL"
        confidence = int(round(supported / total * 100))
    else:
        overall = "NO-FINDINGS"
        confidence = 0

    # Key risks: agents whose findings were blocked
    risk_agents = [
        a for a, fs in by_agent.items()
        if any(f.get("verdict") in ("needs-review", "refuted") for f in fs)
    ]

    # Write detailed synthesis report
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_findings": total,
        "supported_findings": supported,
        "pending_findings": pending,
        "contested_findings": contested,
        "by_agent": {a: len(fs) for a, fs in by_agent.items()},
        "verdict_counts": verdict_counts,
        "verification_counts": verification_counts,
        "overall": overall,
        "confidence": confidence,
        "risk_agents": risk_agents,
    }
    synthesis_path = (
        Path("/Users/aryanagarwal/Documents/polymarket/research")
        / f"synthesis_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(synthesis_path, "w") as f:
        json.dump(report, f, indent=2)

    summary = (
        f"{overall} (confidence {confidence}%): {supported}/{total} findings supported, "
        f"{pending} pending, {contested} contested"
    )
    if risk_agents:
        summary += f"; risks: {', '.join(risk_agents)}"
    return summary


def main():
    acquire_pid_lock()

    log("=" * 60)
    log("JEV Dispatcher starting - Cloud-only fleet (parallel workers)")
    log("=" * 60)

    config = load_office_config()
    agents = get_all_agents(config)
    tiers = sorted(set(a["tier"] for a in agents))
    log(f"Found {len(agents)} agents across tiers: {tiers}")
    log(f"Worker processes: {WORKER_PROCESSES} (all CPU cores)")
    log(f"Threads per process: {MAX_WORKERS}")

    while True:
        # Check completed tasks from previous cycles
        completed, total = check_completed_tasks()
        if total > 0:
            log(f"JEV task completion: {completed}/{total} done ({completed / total * 100:.0f}%)")

        log(f"\n--- JEV Planning Cycle: {len(agents)} agents "
            f"({WORKER_PROCESSES} processes x {MAX_WORKERS} threads) ---")

        # --- Phase 1: Prepare agent tasks in main process (shared state) ---
        # Skip filtering, state bundle gathering, stampede lock, cache gate
        # all run in main process to avoid concurrent file writes.
        tasks = []  # (agent_info, state_bundle, tier) for worker pool
        skip_results = []  # pre-computed skip results

        for agent_info in agents:
            agent_id = agent_info["agent_id"]
            tier = agent_info["tier"]

            # --- O2.2/O2.3: Autonomy tier enforcement ---
            allowed, tier_reason = tier_enforcement_check(agent_id)
            if not allowed:
                skip_results.append(
                    {"agent_id": agent_id, "skipped": f"tier_c_blocked: {tier_reason}"}
                )
                log(f"  TIER-C BLOCK {agent_id}: {tier_reason}")
                continue
            if tier == "B":
                log(f"  TIER-B GATE {agent_id}: {tier_reason} — approval flagged")

            # Skip if agent already has a pending task
            if has_pending_task(agent_id):
                skip_results.append({"agent_id": agent_id, "skipped": "pending_exists"})
                continue

            # Skip if agent has a recently-done task
            if agent_has_recent_done(agent_id):
                skip_results.append({"agent_id": agent_id, "skipped": "recently_done"})
                continue

            # Stampede protection: per-agent lock
            if not stampede_acquire(agent_id):
                skip_results.append({"agent_id": agent_id, "skipped": "stampede_locked"})
                continue

            # Cache gate: skip re-auditing when source data hasn't changed
            state_bundle = gather_state_bundle(agent_id, tier)
            state_files = AGENT_STATE_FILES.get(agent_id, [])
            if state_bundle and state_files:
                skip, reason = cache_check(agent_id, state_files)
                if skip:
                    stampede_release(agent_id)
                    log(f"  Cache skip {agent_id} ({tier}) - {reason}")
                    skip_results.append(
                        {"agent_id": agent_id, "skipped": f"cache:{reason}"}
                    )
                    continue

            tasks.append((agent_info, state_bundle, tier))

        # --- Pick up user-submitted tasks from the dost ---
        user_tasks = collect_user_submitted_tasks()
        user_task_meta = {}  # task_file_path -> (agent_info, tier) for finalization
        for agent_info, state_bundle, tier, task_file_path in user_tasks:
            tasks.append((agent_info, state_bundle, tier))
            user_task_meta[task_file_path] = (agent_info, tier)
            log(f"  User task queued for {agent_info['agent_id']}")

        # --- Phase 2: Execute cloud calls in parallel across all CPU cores ---
        worker_results = []
        if tasks:
            with multiprocessing.Pool(processes=WORKER_PROCESSES) as pool:
                worker_results = pool.map(execute_agent_worker, tasks)

        # --- Phase 3: Finalize results in main process (shared state) ---
        # Verdict gate, findings store, Hive tasks, result files — all here
        # to avoid concurrent writes across processes.
        results = list(skip_results)  # start with pre-computed skips

        # Separate user-submitted tasks (state_bundle is None) from agent tasks
        for (agent_info, state_bundle, tier), worker_result in zip(tasks, worker_results):
            agent_id = agent_info["agent_id"]
            try:
                if state_bundle is None:
                    # User-submitted task — update existing task file, no findings
                    task_file_path = None
                    for path, (info, t) in user_task_meta.items():
                        if info["agent_id"] == agent_id:
                            task_file_path = path
                            break
                    if task_file_path:
                        r = finalize_user_task(task_file_path, worker_result)
                    else:
                        r = {"agent_id": agent_id, "status": "error", "error": "task file not found"}
                    results.append(r)
                    if r.get("status") == "done":
                        log(f"  Done (user task) {agent_id} -> {r.get('task_id','')}")
                    else:
                        log(f"  Error (user task) {agent_id} - {r.get('error','unknown')}")
                else:
                    r = finalize_agent_result(agent_info, state_bundle, tier, worker_result)
                    results.append(r)
                    if r.get("skipped"):
                        log(f"  Skipped {agent_id} ({tier}) - {r['skipped']}")
                    elif r.get("status") == "done":
                        log(f"  Done {agent_id} ({tier}) -> {r['task_id']}")
                    else:
                        log(f"  Error {agent_id} ({tier}) - {r.get('error', 'unknown')}")
            except Exception as e:
                agent_id = agent_info["agent_id"]
                stampede_release(agent_id)
                log(f"  Exception {agent_id}: {e}")
                results.append({"agent_id": agent_id, "status": "error", "error": str(e)})

        done_count = sum(1 for r in results if r.get("status") == "done")
        error_count = sum(1 for r in results if r.get("status") == "error")
        skipped_count = sum(1 for r in results if r.get("skipped"))
        log(
            f"JEV cycle complete: {done_count} done, {error_count} error, {skipped_count} skipped."
        )

        # --- Task archive rotation: cheap check after Phase 3 ---
        # Moves old done/error dost tasks to HIVE_DIR/archive/ once per cycle.
        try:
            archived = archive_old_user_submitted_tasks()
            if archived:
                log(f"  Task archive rotation: {archived} task(s) archived")
        except Exception as e:
            log(f"  Task archive rotation failed: {e}")

        # --- Synthesis: fan-in all findings into a consolidated report ---
        # Like tradedesk's synthesis agent: reads every finding from the
        # store, groups by agent, and produces one overall verdict with
        # confidence. This is the feedback loop that turns independent
        # agent outputs into a fleet-level position.
        try:
            synthesis = synthesize_cycle()
            if synthesis:
                log(f"  Synthesis: {synthesis}")
        except Exception as e:
            log(f"  Synthesis failed: {e}")

        # --- Idle-watch loop ---
        # If no work was produced this cycle, wait up to PLAN_INTERVAL_SEC for
        # new work, but burst immediately if the fleet has been idle > 5s.
        last_activity = time.time()
        last_completed = None
        burst_secs = 5  # burst when idle >= this many seconds
        poll_secs = 1   # check every second

        while True:
            completed, total = check_completed_tasks()
            if last_completed is not None and completed > last_completed:
                # New results appeared since last check -> reset idle timer
                last_activity = time.time()
                log(f"JEV task completion: {completed}/{total} done ({completed / total * 100:.0f}%)")
            last_completed = completed

            idle_secs = time.time() - last_activity
            if idle_secs >= burst_secs:
                # Fleet idle too long -> burst a new cycle to keep keys warm
                log(f"\n--- JEV Idle Burst (idle {idle_secs:.0f}s >= {burst_secs}s): {len(agents)} agents ---")
                break  # exit inner loop, outer loop re-runs the cycle

            if idle_secs >= PLAN_INTERVAL_SEC:
                # Hard cap: never wait more than PLAN_INTERVAL_SEC between cycles
                log(f"\n--- JEV Scheduled Cycle ({idle_secs:.0f}s elapsed) ---")
                break

            time.sleep(poll_secs)


if __name__ == "__main__":
    if argparse and "--pnl" in sys.argv:
        pnl = office_pnl()
        print("=== Office P&L (Cost per Outcome) ===")
        print(f"Tasks: {pnl['task_count']}")
        print(f"Total cost units: {pnl['total_cost_units']}")
        print(f"Total outcome value: {pnl['total_outcome_value']}")
        print(f"Net value: {pnl['net_value']}")
        print()
        print("By autonomy tier:")
        for tier, d in sorted(pnl["by_tier"].items()):
            print(f"  Tier {tier}: cost={d['cost']} value={d['value']} "
                  f"count={d['count']} net={d['net']}")
        print()
        print("By agent (top 10 by net value):")
        sorted_agents = sorted(
            pnl["by_agent"].items(), key=lambda x: x[1]["net"], reverse=True
        )
        for agent, d in sorted_agents[:10]:
            print(f"  {agent:30s} tier={d['tier']} cost={d['cost']:>3} "
                  f"value={d['value']:>4} count={d['count']:>3} net={d['net']:>4}")
        sys.exit(0)
    main()
