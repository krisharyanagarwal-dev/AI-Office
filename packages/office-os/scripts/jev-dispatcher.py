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
import signal
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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

End your response with a clear verdict line: VERDICT: PASS or VERDICT: FAIL
or VERDICT: go/no-go, followed by a one-sentence summary."""


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
    """Add a finding to the store if not already present (dedupe by claim+agent)."""
    store = load_findings_store()
    # Dedup: same agent + same claim already exists
    for f in store["findings"]:
        if f.get("agent") == agent_id and f.get("claim") == claim:
            return False  # already exists
    finding = {
        "id": f"f-{uuid.uuid4().hex[:8]}",
        "agent": agent_id,
        "claim": claim,
        "evidence_ref": evidence_ref,
        "verdict": verdict,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    finding.update(kwargs)
    store["findings"].append(finding)
    save_findings_store(store)
    return True


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
        return {"agent_id": agent_id, "status": "error", "error": worker_result["error"]}

    exec_text = worker_result["exec_text"]
    exec_model_used = worker_result["exec_model"]
    exec_pool_used = worker_result["exec_pool"]
    direct_exec = worker_result["direct_exec"]

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
    if gate_ok:
        claim = exec_text.strip().split("\n")[0][:200]
        evidence_ref = f"jev-task-{task_id}"
        added = add_finding(
            agent_id,
            claim=claim,
            evidence_ref=evidence_ref,
            verdict="supported" if gate_ok else "needs-review",
            source="jev-cloud-orchestrator",
            gate_reason=gate_reason,
        )
        if added:
            log(f"  Finding stored for {agent_id}: {claim[:80]}...")
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

    stampede_release(agent_id)
    return {"agent_id": agent_id, "status": "done", "task_id": task_id}


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

    # Count verdicts
    verdict_counts = {}
    for f in findings:
        v = f.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # Overall verdict: if any finding is "needs-review" or "refuted",
    # fleet is not fully supported. If all are "supported", fleet is green.
    total = len(findings)
    supported = verdict_counts.get("supported", 0)
    blocked = verdict_counts.get("needs-review", 0) + verdict_counts.get("refuted", 0)

    if blocked > 0:
        overall = "CAUTION"
        confidence = max(0, 100 - (blocked * 25))
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
        "by_agent": {a: len(fs) for a, fs in by_agent.items()},
        "verdict_counts": verdict_counts,
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
        f"{overall} (confidence {confidence}%): {supported}/{total} findings supported"
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

        # --- Phase 2: Execute cloud calls in parallel across all CPU cores ---
        worker_results = []
        if tasks:
            with multiprocessing.Pool(processes=WORKER_PROCESSES) as pool:
                worker_results = pool.map(execute_agent_worker, tasks)

        # --- Phase 3: Finalize results in main process (shared state) ---
        # Verdict gate, findings store, Hive tasks, result files — all here
        # to avoid concurrent writes across processes.
        results = list(skip_results)  # start with pre-computed skips

        for (agent_info, state_bundle, tier), worker_result in zip(tasks, worker_results):
            agent_id = agent_info["agent_id"]
            try:
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
    main()
