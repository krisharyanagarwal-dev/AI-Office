#!/usr/bin/env python3
"""THE CLAUDE COMPANY — Dost Interface.

Personal AI chief of staff. Natural language in, natural language out.
The LLM generates warm, dynamic responses grounded in live company data.
Numbers are injected verbatim from files; the LLM only narrates.

Paper only. Kill switch locked. No live orders ever.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import glob
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent.parent
DOST_DIR = Path(__file__).resolve().parent
DOST_MEMORY = DOST_DIR / "memory.json"
DOST_HISTORY = DOST_DIR / "history.jsonl"
DOST_BRIEFINGS = DOST_DIR / "briefings"
DOST_TEMPLATES = DOST_DIR / "templates"
DOST_DIR.mkdir(parents=True, exist_ok=True)
DOST_BRIEFINGS.mkdir(parents=True, exist_ok=True)
DOST_TEMPLATES.mkdir(parents=True, exist_ok=True)

# Alert webhook URL — optional, read from env or config file.
ALERT_WEBHOOK_URL = None
_webhook_path = Path.home() / ".openclaw" / "alert_webhook.json"
if _webhook_path.exists():
    try:
        ALERT_WEBHOOK_URL = json.loads(_webhook_path.read_text()).get("url")
    except Exception:
        pass
if not ALERT_WEBHOOK_URL:
    ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL")

sys.path.insert(0, str(COMPANY_DIR))
sys.path.insert(0, str(DOST_DIR))
from company_dispatcher import dispatch, route_department  # noqa: E402
from openai_components import chat_completion, provider_health  # noqa: E402
from context_builder import build_context  # noqa: E402
from collab.workspace import (  # noqa: E402
    create_workspace,
    get_workspace,
    list_workspaces,
    add_user,
    list_users,
    get_user_role,
    workspace_tasks_dir,
    ensure_default_workspace,
    DEFAULT_WORKSPACE_ID,
)

# Cloud model orchestrator (same orchestration the dispatcher uses) for direct
# debate calls that bypass the dispatcher's general-assistant override.
OFFICE_OS = (Path(__file__).resolve().parents[1] / "packages" / "office-os")
if str(OFFICE_OS) not in sys.path:
    sys.path.insert(0, str(OFFICE_OS))
from core.subs.cloud_orchestrator import CloudModelOrchestrator  # noqa: E402

RESEARCH_DIR = (Path.home() / "Documents" / "indian-paper-trading")
O3_RUNNER = RESEARCH_DIR / "o3_runner.py"

RESEARCH_COMMANDS = {"register", "gate", "holdout", "calibrate", "report", "all"}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts}: {msg}", flush=True)


class DostMemory:
    """Persistent user profile + conversation history."""

    def __init__(self):
        self.profile = self._load(DOST_MEMORY, {
            "name": "Aryan",
            "capital_inr": 100000,
            "risk_tolerance": "conservative",
            "preferred_markets": ["NSE"],
            "goals": ["honest research", "cost-aware trading", "self-improving systems"],
            "boundaries": {
                "paper_only": True,
                "kill_switch_locked": True,
                "no_live_orders": True,
            },
            "research_interests": ["options selling", "defined risk spreads", "IV rank"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self.history = []

    def _load(self, path, default):
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def save(self):
        DOST_MEMORY.write_text(json.dumps(self.profile, indent=2))

    def update(self, **kwargs):
        self.profile.update(kwargs)
        self.save()

    def add_interaction(self, user_input, department, summary):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user_input,
            "department": department,
            "summary": summary,
        }
        self.history.append(entry)
        with open(DOST_HISTORY, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if len(self.history) > 200:
            self.history = self.history[-200:]


MEMORY = DostMemory()


def dost_greeting():
    hour = datetime.now().hour
    gm = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    return f"{gm}, {MEMORY.profile['name']}. I'm your dost from THE CLAUDE COMPANY. How can I help you today?"


def run_research_command(cmd: str) -> str:
    """Execute a real o3_runner.py command and return raw output."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, str(O3_RUNNER), cmd],
            capture_output=True, text=True, timeout=120,
            cwd=str(RESEARCH_DIR),
        )
        output = result.stdout or result.stderr
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out (>120s)."
    except Exception as e:
        return f"Error running research command: {e}"


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

DECIDE_SYSTEM = """You are the dost from THE CLAUDE COMPANY — a warm, honest AI chief of staff.

CONTEXT (live company data — use these verbatim for any numbers):
{context}

The user said: "{task}"

Decide how to respond:
- If they're asking to run a research pipeline command (report/register/gate/holdout/calibrate/all), reply with ONLY: COMMAND:<command_name>
- Otherwise, write a warm, natural response in your own voice. Ground any numbers in the CONTEXT above. Be honest about failures — don't hide them. Don't expose internal IDs, provider names, model names, task IDs, or technical plumbing. Sound like a capable friend who knows about trading research.
"""


NARRATE_SYSTEM = """You are the dost from THE CLAUDE COMPANY — a warm, honest AI chief of staff.

CONTEXT (live company data — use these verbatim for any numbers):
{context}

I just ran this research command: {command}
Here's the raw output:
{output}

Narrate this in your warm, honest voice. Ground every number in the data. Don't hallucinate. If the command failed or found nothing, say so plainly. Don't expose internal IDs, provider names, model names, task IDs, or technical plumbing.
"""


def llm_decide(task: str, context: str, style: str = "") -> str:
    """Ask the LLM whether this is a command or conversation. Returns 'COMMAND:<name>' or natural text."""
    prompt = DECIDE_SYSTEM.format(context=context, task=task)
    if style:
        prompt += "\n\nSTYLE:\n" + style
    result = chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": task},
        ],
        temperature=0.3,
        max_tokens=400,
    )
    text = result["text"].strip()
    return text


def llm_narrate(command: str, output: str, context: str) -> str:
    """Ask the LLM to narrate command output in its warm voice."""
    prompt = NARRATE_SYSTEM.format(context=context, command=command, output=output)
    result = chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Narrate the output of the {command} command."},
        ],
        temperature=0.4,
        max_tokens=500,
    )
    return result["text"].strip()


# ---------------------------------------------------------------------------
# Deterministic fallbacks (when no LLM provider is available)
# ---------------------------------------------------------------------------

def fallback_decide(task: str, context: str) -> str:
    """Keyword-based decision when no LLM is available."""
    t = task.strip().lower()
    if t in RESEARCH_COMMANDS:
        return f"COMMAND:{t}"
    return None  # signal to use fallback_converse


def fallback_converse(task: str, context: str) -> str:
    """Deterministic warm response when no LLM is available."""
    t = task.strip().lower()
    if any(k in t for k in ["research", "hypothesis", "edge", "strategy", "backtest", "bull put", "iv rank"]):
        return (
            "I can help you run honest, cost-aware research on NSE ideas. "
            "Tell me a hypothesis (like 'bull put spreads with IV rank above 80%'), and I'll pre-register it, "
            "backtest it with real Groww costs, check it against out-of-sample data, and give you a plain-language "
            "verdict — including if it doesn't work. Want to try one?"
        )
    if any(k in t for k in ["trading", "paper", "cost", "groww", "capital", "₹1", "1 lakh"]):
        return (
            "The trading desk is paper-only right now — every backtest uses real Groww costs, so nothing is overstated. "
            "Key finding: no viable edge at ₹1 lakh + free data across multiple strategy variants and market regimes. "
            "The paper engine is ready if your capital grows to ₹5L+, where naked options selling does have an edge."
        )
    if any(k in t for k in ["fleet", "agent", "kill switch", "verification"]):
        return (
            "Behind the scenes, the fleet runs paper-only. The kill switch is locked, Tier C (risk, "
            "execution, broker) is human-only, and no finding gets confirmed without independent verification."
        )
    if any(k in t for k in ["ops", "pnl", "health", "provider", "dashboard", "metrics"]):
        st = _fetch_dispatcher_status()
        if st:
            return (
                "Fleet is live right now: "
                f"{st['tasks_done']}/{st['tasks_created']} tasks done "
                f"({st['completion_rate']:.0f}% complete), error rate {st['error_rate_total']:.1f}%, "
                f"{st['calls_today']} calls today, {st['pools_available']} provider pools available. "
                "Run 'python dost.py --status' for the full readout, or 'python dost.py --dispatch' "
                "to send a prompt to the fleet."
            )
        return (
            "I track the company's health: cost-per-outcome P&L, autonomy tiers, provider health, dashboards. "
            "Run 'python company.py pnl' or 'python company.py metrics' anytime. What would you like to look at?"
        )
    if any(k in t for k in ["upgrade", "refactor", "test", "codebase"]):
        return (
            "The company upgrades itself — code, prompts, configs, processes — but never without tests passing first. "
            "Every change goes through: test → apply → test again → rollback if it breaks. Want to see the upgrade candidates?"
        )
    if any(k in t for k in ["write", "memo", "code", "analyze", "strategy", "plan", "debug"]):
        return (
            "I can help with code, writing, analysis, strategy, debugging, and planning. "
            "Just tell me what you need built or fixed, and I'll get on it. What's on your mind?"
        )
    return (
        "I'm your dost from THE CLAUDE COMPANY. I can help with research, trading analysis, fleet operations, "
        "company health, self-upgrades, or general assistant tasks. What would you like to focus on?"
    )


def fallback_narrate(command: str, output: str) -> str:
    """Deterministic narration of command output when no LLM is available."""
    # Try to extract key numbers for a honest one-liner
    lines = output.strip().split("\n")
    summary = []
    for line in lines:
        if any(k in line.lower() for k in ["passed", "failed", "net_pnl", "total_net", "confirmed", "well-calibrated"]):
            summary.append(line.strip())
    if summary:
        return ("Here's what I found:\n\n" + "\n".join(summary[:5]) +
                "\n\nThe full output is above. What would you like to do next?")
    return (
        f"Here's the output from the {command} command:\n\n{output[:800]}\n\n"
        "What would you like to do next?"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def dost_respond(task, department=None):
    context = build_context()
    conv = _conversation_prefix()
    if conv:
        context = f"{context}\n\n{conv}"

    # Ask the LLM to decide: command or conversation?
    decision = llm_decide(task, context)

    if decision and decision.startswith("COMMAND:"):
        command = decision[len("COMMAND:"):].strip()
        if command in RESEARCH_COMMANDS:
            output = run_research_command(command)
            MEMORY.add_interaction(task, "research", f"Executed research command: {command}")
            # Narrate the output with the LLM
            narration = llm_narrate(command, output, context)
            if narration:
                response = f"{dost_greeting()}\n\n{narration}\n\nWhat would you like to do next?"
            else:
                response = f"{dost_greeting()}\n\n{fallback_narrate(command, output)}"
            _record_conversation_turn(task, response)
            return response

    # Not a command — have the LLM write a warm conversational response
    if decision and not decision.startswith("COMMAND:"):
        # LLM already gave us a natural response
        MEMORY.add_interaction(task, route_department(task), "Conversational response")
        _record_conversation_turn(task, decision)
        return f"{dost_greeting()}\n\n{decision}\n\nIs there anything else I can help you with?"

    # Fallback: no LLM available or decision unparseable
    fb = fallback_decide(task, context)
    if fb and fb.startswith("COMMAND:"):
        command = fb[len("COMMAND:"):].strip()
        output = run_research_command(command)
        MEMORY.add_interaction(task, "research", f"Executed research command: {command} (fallback)")
        response = f"{dost_greeting()}\n\n{fallback_narrate(command, output)}"
        _record_conversation_turn(task, response)
        return response

    response = fallback_converse(task, context)
    MEMORY.add_interaction(task, route_department(task), "Conversational response (fallback)")
    _record_conversation_turn(task, response)
    return f"{dost_greeting()}\n\n{response}\n\nIs there anything else I can help you with?"


COMPANION_STYLE = """Talk like a close, warm friend who also happens to run the research team.
- Keep replies short: 2-4 sentences, unless the person asks for detail.
- Match their language and energy. A casual "hi" gets a casual reply.
- Use their name now and then, not every line.
- No bullet lists, headings or sign-offs unless they ask for them.
- Never end with "anything else I can help with" or similar.
- Be honest about losses and failures, but kind about it.
- Ground any numbers in the CONTEXT and never invent them.
- Remember what the person has told you across this conversation and refer back to it naturally.
- If you're not sure about something, say so rather than guessing.

FACTS ABOUT YOURSELF (these override the rule about hiding models and plumbing;
answer questions about yourself from these facts only, and say "I don't know"
for anything not covered):
- Your brain is a free hosted model. Each message goes to the first provider
  that answers.
- You are connected to the company's fleet orchestrator. You can read live
  fleet status and submit prompts to the fleet for execution.
- What you can see: the research hypothesis results, the calibration ledger,
  the office P&L summary, the fleet task summary, and live fleet status in
  the CONTEXT.
- What you can do: chat, run a read-only system audit when asked to "audit"
  or "check the system", run the research pipeline commands register,
  gate, holdout, calibrate, report and all (only when asked by name), and
  submit prompts to the fleet orchestrator.
- What you cannot do: place trades (paper only, live orders locked), edit
  files, start or stop services, or control other systems on the computer.
  Never claim you are "going live" beyond the fleet connection.
- You remember past conversations in this chat window. If the person refers
  to something earlier, use that context.
- You are paper-only: every backtest uses real Groww costs, nothing is
  overstated. The kill switch is locked and Tier C is human-only."""

DISPATCHER_METRICS_URL = "http://127.0.0.1:8083/metrics"
HIVE_DIR = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "tasks")
OFFICE_CONFIG_PATH = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "config" / "office.json")


# --- Advisory daily cost cap -------------------------------------------------
# The fleet books synthetic cost units per task. The daily ceiling is read from
# office.json so it can track fleet scale, and it stays advisory: it warns, it
# never halts dispatch.

def cost_cap_limit() -> int | None:
    try:
        cfg = json.loads(OFFICE_CONFIG_PATH.read_text())
        cap = (cfg.get("cost_cap") or {}) if isinstance(cfg, dict) else {}
        value = cap.get("daily_units")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = int(value)
        return value if value > 0 else None
    except Exception:
        return None


def cost_cap_status(cost_units: float, limit: int | None = None) -> tuple[bool, str]:
    if limit is None:
        limit = cost_cap_limit()
    detail = f"Today's cost: {cost_units} units"
    if limit is None:
        return True, f"{detail} — no cap configured (advisory only)"
    if cost_units > limit:
        return False, f"{detail} — COST CAP EXCEEDED ({limit} units, advisory)"
    if cost_units > limit * 0.8:
        return True, f"{detail} — approaching cap ({limit} units)"
    return True, f"{detail} (cap {limit} units)"


def _daily_cost_check(pnl_path: Path) -> tuple[bool, str]:
    try:
        if not pnl_path.exists():
            return True, "no P&L file"
        pnl = json.loads(pnl_path.read_text())
        if not isinstance(pnl, list):
            return True, "no P&L data"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_cost = sum(
            t.get("cost_units", 0)
            for t in pnl
            if isinstance(t, dict) and str(t.get("created_at", "")).startswith(today)
        )
        return cost_cap_status(today_cost)
    except Exception as e:
        return False, f"cost cap check failed ({e})"


# --- Local provider verification ---------------------------------------------
# The dispatcher reports pool availability from its own state, so a local pool
# can read "available" while its server is down. Local pools are probed
# directly so unverifiable is reported as not-verified, never as up.

LOCAL_POOL_ENDPOINTS = {
    "mlx_local": "http://127.0.0.1:11435/v1/models",
}


def probe_local_pools(timeout: float = 3.0) -> dict[str, str]:
    status = {}
    for name, url in LOCAL_POOL_ENDPOINTS.items():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                status[name] = "up" if getattr(response, "status", 0) == 200 else "not-verified"
        except Exception:
            status[name] = "not-verified"
    return status


def summarize_provider_pools(
    pools: dict, local_status: dict | None = None
) -> tuple[bool, str]:
    local_status = local_status or {}
    parts = []
    ok = True
    for pname, pinfo in pools.items():
        avail = pinfo.get("available", False)
        cd = pinfo.get("cooldown_remaining", 0)
        if pname in local_status:
            state = local_status[pname]
            if state != "up":
                ok = False
                parts.append(f"{pname}:{state}")
            elif avail and cd == 0:
                parts.append(f"{pname}:up")
            elif cd > 0:
                ok = False
                parts.append(f"{pname}:cooling({cd}s)")
            else:
                ok = False
                parts.append(f"{pname}:down")
        elif avail and cd == 0:
            parts.append(f"{pname}:up")
        elif cd > 0:
            ok = False
            parts.append(f"{pname}:cooling({cd}s)")
        else:
            ok = False
            parts.append(f"{pname}:down")
    if not pools:
        ok = False
        parts.append("no pools")
    return ok, ", ".join(parts) if parts else "unknown"


# Default pro-tier agents for general debate questions (all exist in office.json
# agent_tiers under "pro"). data-analyst suggested in the spec does not exist,
# so we fall back to available pro-tier agents.
DEBATE_DEFAULT_AGENTS = ["strategy-advisor", "cost-analyst", "risk-manager"]


# --- Debate cost accounting -------------------------------------------------
# Debate calls bypass the dispatcher (direct CloudModelOrchestrator), so they
# never hit the dispatcher's record_task_outcome(). Log them here so they
# appear in office_pnl.json with source="debate" instead of being a blind spot.

TASK_LEDGER_PATH = (Path.home() / ".openclaw" / "office_pnl.json")

MODEL_COST_UNITS = {
    "pro": 3,
    "general": 2,
    "lite": 1,
}


def _load_task_ledger() -> list[dict]:
    try:
        with open(TASK_LEDGER_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_task_ledger(ledger: list[dict]) -> None:
    tmp = str(TASK_LEDGER_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, TASK_LEDGER_PATH)


def _pool_tier_from_config(pool_name: str) -> str | None:
    """Look up the tier string for a provider pool from office.json."""
    try:
        config = json.loads(OFFICE_CONFIG_PATH.read_text())
        pools = config.get("provider_pools", {})
        pinfo = pools.get(pool_name)
        if pinfo:
            return pinfo.get("tier")
    except Exception:
        pass
    return None


def _cost_units_for_pool(pool_name: str | None) -> int:
    if not pool_name:
        return 2
    tier = _pool_tier_from_config(pool_name)
    if isinstance(tier, list):
        return min(MODEL_COST_UNITS.get(t, 2) for t in tier)
    return MODEL_COST_UNITS.get(tier, 2)


def _record_debate_to_pnl(
    task_id: str,
    agent_id: str,
    tier: str,
    status: str,
    cost_units: int,
    pool_name: str | None,
    created_at: str,
) -> None:
    """Append a debate-call record to the office P&L ledger.

    Mirrors the dispatcher's record_task_outcome() format so debate calls
    appear in office_pnl.json alongside dispatcher tasks (source="debate").
    Debate produces no verifiable outcome, so outcome_value=0 and
    net_value=-cost_units (cost only).
    """
    ledger = _load_task_ledger()
    ledger.append(
        {
            "task_id": task_id,
            "agent_id": agent_id,
            "autonomy_tier": tier,
            "status": status,
            "cost_units": cost_units,
            "outcome_value": 0,
            "net_value": -cost_units,
            "created_at": created_at,
            "source": "debate",
            "pool": pool_name,
        }
    )
    _save_task_ledger(ledger)


def _check_pool_cooldowns() -> dict[str, int]:
    """Read :8083/metrics and return {pool_name: cooldown_remaining_seconds}.

    Used before debate/dispatch calls so we know which pools the dispatcher
    is cooling down. Debate and voice dispatch have their own orchestrator
    instance with separate cooldown state from the dispatcher.
    """
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        pools = data.get("provider_pools", {})
        return {p: pinfo.get("cooldown_remaining", 0) for p, pinfo in pools.items()}
    except Exception:
        return {}


def _select_available_pool(
    orchestrator: CloudModelOrchestrator,
    agent_info: dict,
    pool_cooldowns: dict[str, int],
    max_attempts: int = 5,
) -> tuple[str, str, bool]:
    """Pick a model/pool via decide_model, avoiding cooled-down pools.

    decide_model round-robins across all pools. If it returns a pool that's
    currently cooling down, retry decide_model (different pool next time) up
    to max_attempts. Returns (model, pool_name, is_cloud).
    """
    for _ in range(max_attempts):
        model, pool_name, is_cloud = orchestrator.decide_model(agent_info, task_type="exec")
        if pool_cooldowns.get(pool_name, 0) == 0:
            return model, pool_name, is_cloud
    # All attempts hit cooled pools — return the last one anyway (best effort)
    return model, pool_name, is_cloud


def _call_with_retry(
    orchestrator: CloudModelOrchestrator,
    agent_info: dict,
    full_prompt: str,
    task_id: str,
    pool_cooldowns: dict[str, int],
    max_retries: int = 2,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Call a model with cooldown-aware pool selection and auto-retry.

    On provider failure (410, quota, rate-limit), retry once on a different
    pool via decide_model round-robin. Returns
    (response_text, model_used, pool_used, error).
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            model, pool_name, _ = _select_available_pool(
                orchestrator, agent_info, pool_cooldowns
            )
            response_text, model_used, pool_used = orchestrator.call_model(
                model, pool_name, full_prompt, task_id=task_id, priority="normal",
            )
            return response_text, model_used, pool_used, None
        except Exception as e:
            last_error = str(e)
            # Refresh cooldowns before retry (pool may have just cooled/heated)
            pool_cooldowns = _check_pool_cooldowns()
            continue
    return None, None, None, last_error


# --- Findings store hygiene -------------------------------------------------
# The findings store accumulates task instructions and echo fragments alongside
# real findings. These helpers detect junk (non-finding) entries and collapse
# duplicate claims so Tier C review is faster and synthesis confidence is
# meaningful. All read + write to findings.json atomically.

JUNK_PATTERNS = [
    "we need",
    "need answer as jev",
    "jev executing",
    "audit task",
    "finding and verdict",
    "title:",
    "based on the provided state bundle",
    "structured findings with specific numbers",
    "end with finding and verdict",
    "what verdict?",
]

FINDINGS_STORE_PATH = str(Path.home() / "Documents" / "polymarket" / "research" / "findings.json")


def _load_findings_store() -> dict:
    """Load the findings store, creating it if needed."""
    try:
        with open(FINDINGS_STORE_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "findings" not in data:
            return {"findings": []}
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"findings": []}


def _save_findings_store(store: dict) -> None:
    """Atomically write the findings store."""
    tmp = FINDINGS_STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2, sort_keys=True)
    os.replace(tmp, FINDINGS_STORE_PATH)


def _is_junk_finding(finding: dict) -> bool:
    """Return True if a finding looks like a task instruction, not a real finding."""
    claim = (finding.get("claim") or "").lower()
    evidence = (finding.get("evidence_ref") or "").lower()
    combined = f"{claim} {evidence}"
    for pattern in JUNK_PATTERNS:
        if pattern in combined:
            return True
    # Findings with no verification_status and very short claims are likely junk
    if not finding.get("verification_status") and len(claim.strip()) < 20:
        return True
    return False


def detect_junk_findings(store: dict | None = None) -> list[dict]:
    """Scan findings and return those that look like task instructions/echoes.

    Each returned dict includes the finding index, agent, claim, and the
    matched junk pattern. Caller decides what to do (flag, skip, delete).
    """
    if store is None:
        store = _load_findings_store()
    junked = []
    for idx, f in enumerate(store.get("findings", [])):
        if _is_junk_finding(f):
            claim = f.get("claim", "")
            matched = next(
                (p for p in JUNK_PATTERNS if p in (claim + " " + f.get("evidence_ref", "")).lower()),
                "short-claim-no-status",
            )
            junked.append(
                {
                    "index": idx,
                    "agent": f.get("agent", "?"),
                    "claim": claim[:120],
                    "matched_pattern": matched,
                    "verification_status": f.get("verification_status", "missing"),
                }
            )
    return junked


def dedup_findings(store: dict | None = None) -> list[dict]:
    """Collapse findings with identical claims into one (keep most recent).

    Returns a list of removed finding indices.
    """
    if store is None:
        store = _load_findings_store()
    findings = store.get("findings", [])
    seen_claims: dict[str, int] = {}  # normalized claim -> index of kept finding
    removed = []
    keep_indices = set(range(len(findings)))
    for idx in range(len(findings) - 1, -1, -1):  # newest first, keep latest
        f = findings[idx]
        claim = (f.get("claim") or "").strip().lower()
        if not claim:
            continue
        if claim in seen_claims:
            removed.append(idx)
            keep_indices.discard(idx)
        else:
            seen_claims[claim] = idx
    if removed:
        store["findings"] = [f for i, f in enumerate(findings) if i in keep_indices]
        _save_findings_store(store)
    return [{"index": i} for i in removed]


def clean_findings_store() -> dict:
    """Run junk detection + dedup on the findings store.

    Junk findings get verification_status set to 'needs-review' (not deleted —
    Tier C decides). Duplicates are removed. Returns a summary dict.
    """
    store = _load_findings_store()
    junked = detect_junk_findings(store)
    # Flag junk findings as needs-review (Tier C decides confirm/contest/skip)
    flagged = 0
    for j in junked:
        idx = j["index"]
        if idx < len(store.get("findings", [])):
            f = store["findings"][idx]
            if f.get("verification_status") not in ("confirmed", "contested"):
                f["verification_status"] = "needs-review"
                flagged += 1
    _save_findings_store(store)
    removed = dedup_findings(store)
    return {
        "junk_detected": len(junked),
        "junk_flagged": flagged,
        "duplicates_removed": len(removed),
        "total_findings": len(store.get("findings", [])),
    }


# --- Tier C review completion ------------------------------------------------
# Human-only verification of findings. Accepts confirm/contest/skip/delete
# calls by finding index, updates verification_status, and re-runs synthesis.
# This is the bottleneck that makes synthesis confidence meaningful.

VALID_REVIEW_ACTIONS = {"confirm", "contest", "skip", "delete"}


def review_findings(actions: list[dict]) -> dict:
    """Apply Tier C review decisions to findings.

    Each action is {"index": int, "action": "confirm"|"contest"|"skip"|"delete"}.
    - confirm/contest/skip: set verification_status accordingly
    - delete: remove the finding from the store entirely

    Returns a summary of what changed and re-runs synthesis.
    Human-only — this function does not make any decisions itself.
    """
    store = _load_findings_store()
    findings = store.get("findings", [])
    applied = []
    deleted_indices = []

    for action in actions:
        idx = action.get("index")
        act = action.get("action", "").lower()
        if act not in VALID_REVIEW_ACTIONS:
            applied.append({"index": idx, "action": act, "error": "invalid action"})
            continue
        if idx is None or not (0 <= idx < len(findings)):
            applied.append({"index": idx, "action": act, "error": "index out of range"})
            continue
        f = findings[idx]
        if act == "delete":
            deleted_indices.append(idx)
            applied.append({"index": idx, "action": "delete", "agent": f.get("agent", "?"),
                            "claim": f.get("claim", "")[:80]})
        else:
            f["verification_status"] = act
            f["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            applied.append({"index": idx, "action": act, "agent": f.get("agent", "?"),
                            "claim": f.get("claim", "")[:80], "status": act})

    # Remove deleted findings (highest index first to preserve positions)
    for idx in sorted(deleted_indices, reverse=True):
        del findings[idx]

    _save_findings_store(store)

    # Re-run synthesis after review
    summary = {
        "actions_applied": len(applied),
        "deleted": len(deleted_indices),
        "details": applied,
    }

    # Recompute verification counts
    vs_counts = {}
    for f in store.get("findings", []):
        v = f.get("verification_status", "missing")
        vs_counts[v] = vs_counts.get(v, 0) + 1
    summary["verification_after"] = vs_counts
    summary["total_after"] = len(store.get("findings", []))

    return summary


# --- Answer cache -----------------------------------------------------------
# Repeat questions (fleet status, completion rate, error rate) return a cached
# answer instead of burning a provider call. TTL 10 minutes.

DOST_ANSWER_CACHE_PATH = str(Path.home() / ".openclaw" / "dost_answer_cache.json")
ANSWER_CACHE_TTL_SEC = 600  # 10 minutes


def _hash_question(question: str) -> str:
    """Normalize and hash a question for cache lookup."""
    import hashlib
    normalized = question.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _load_answer_cache() -> dict:
    """Load the answer cache."""
    try:
        with open(DOST_ANSWER_CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_answer_cache(cache: dict) -> None:
    """Atomically write the answer cache."""
    tmp = DOST_ANSWER_CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, DOST_ANSWER_CACHE_PATH)


def _get_cached_answer(question_hash: str) -> dict | None:
    """Return cached answer if not expired, else None."""
    cache = _load_answer_cache()
    entry = cache.get(question_hash)
    if not entry:
        return None
    try:
        cached_at = float(entry.get("cached_at", 0))
        if time.time() - cached_at > ANSWER_CACHE_TTL_SEC:
            return None
    except (ValueError, TypeError):
        return None
    return entry


def _cache_answer(
    question_hash: str,
    question: str,
    answer_text: str,
    model: str | None,
    pool: str | None,
    cost_units: int,
    debate_id: str | None = None,
    agents: list[dict] | None = None,
    agent_answers: list[dict] | None = None,
    synthesis: str | None = None,
) -> None:
    """Store an answer in the cache."""
    cache = _load_answer_cache()
    cache[question_hash] = {
        "question": question,
        "answer": answer_text or synthesis or "",
        "model": model,
        "pool": pool,
        "cost_units": cost_units,
        "cached_at": time.time(),
        "debate_id": debate_id,
        "agents": agents or [],
        "agent_answers": agent_answers or [],
        "synthesis": synthesis or answer_text or "",
    }
    _save_answer_cache(cache)


# --- Multi-turn conversation memory -----------------------------------------
# Remember last N turns so follow-ups ("and the error rate?") know what
# you're talking about. Stored in dost/conversation.json.

DOST_CONVERSATION_PATH = DOST_DIR / "conversation.json"
DOST_CONVERSATION_TURNS = 3  # how many previous turns to remember


def _load_conversation() -> list[dict]:
    """Load previous conversation turns."""
    try:
        with open(DOST_CONVERSATION_PATH) as f:
            turns = json.load(f)
        if isinstance(turns, list):
            return turns[-DOST_CONVERSATION_TURNS:]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save_conversation(turns: list[dict]) -> None:
    """Atomically write conversation turns."""
    tmp = str(DOST_CONVERSATION_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(turns[-DOST_CONVERSATION_TURNS:], f, indent=2)
    os.replace(tmp, DOST_CONVERSATION_PATH)


def _conversation_prefix() -> str:
    """Format previous turns as a context prefix for the LLM."""
    turns = _load_conversation()
    if not turns:
        return ""
    lines = ["PREVIOUS CONVERSATION:"]
    for t in turns:
        user = t.get("user", "")
        resp = t.get("response", "")
        lines.append(f"  User: {user[:120]}")
        lines.append(f"  Dost: {resp[:200]}")
    lines.append("---")
    return "\n".join(lines)


def _record_conversation_turn(user: str, response: str) -> None:
    """Append a turn to the conversation history."""
    turns = _load_conversation()
    turns.append(
        {
            "user": user,
            "response": response,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    _save_conversation(turns)


def _agent_tiers() -> dict[str, str]:
    """Return {agent_id: tier} loaded from office.json agent_tiers."""
    tiers: dict[str, str] = {}
    try:
        config = json.loads(OFFICE_CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return tiers
    for tier, tier_agents in (config.get("agent_tiers") or {}).items():
        if isinstance(tier_agents, list):
            for agent_id in tier_agents:
                tiers[agent_id] = tier
    return tiers


def wants_audit(task: str) -> bool:
    t = task.lower()
    return any(w in t for w in AUDIT_WORDS)


AUDIT_WORDS = ["audit", "check the system", "system health", "is everything ok", "anything wrong", "any alerts"]


def run_system_audit() -> list:
    """Read-only survey of the office systems (same collectors the orchestrator uses)."""
    if str(OFFICE_CORE) not in sys.path:
        sys.path.insert(0, str(OFFICE_CORE))
    import sources  # noqa: E402  (office-os read-only collectors)
    return sources.collect_all()


def _fetch_dispatcher_status() -> dict | None:
    """Read live fleet status from the dispatcher metrics endpoint.

    Returns a dict with key status fields, or None if unreachable.
    Read-only — never sends commands to the dispatcher.
    """
    try:
        with urllib.request.urlopen(DISPATCHER_METRICS_URL, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        jev = data.get("jev", {})
        pools = data.get("provider_pools", {})
        available = sum(1 for p in pools.values() if p.get("available"))
        total = len(pools)
        return {
            "tasks_created": jev.get("tasks_created", 0),
            "tasks_done": jev.get("tasks_done", 0),
            "completion_rate": jev.get("completion_rate", 0),
            "error_rate": jev.get("error_rate", 0),
            "error_rate_total": jev.get("error_rate_total", 0),
            "tasks_per_min": jev.get("tasks_per_min", 0),
            "calls_today": jev.get("calls_today", 0),
            "headroom_pct": data.get("free_ceiling", {}).get("headroom_pct", 0),
            "pools_available": f"{available}/{total}",
        }
    except Exception:
        return None


def dispatch_prompt_to_fleet(
    prompt: str,
    agent_id: str | None = None,
    priority: str = "normal",
    dry_run: bool = False,
    parent_task_id: str | None = None,
    chain: dict | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Submit a prompt to the fleet orchestrator by writing a task file.

    The dispatcher picks up pending task files from HIVE_DIR on each cycle
    and executes them through the cloud orchestrator. Returns the task info.
    Read-only data write — no live orders, no trading execution.

    If dry_run is True, shows what would be dispatched without writing.
    If parent_task_id is given, this task is threaded under that parent
    (task threading / multi-turn follow-up).
    If chain is given (dict with prompt/agent_id/priority), the dispatcher
    auto-dispatches a follow-up task when this task completes (done).
    """
    import uuid

    task_id = f"jev-{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "title": f"Dost prompt: {prompt[:60]}",
        "description": prompt,
        "status": "pending",
        "agent_id": agent_id or "strategy-advisor",
        "priority": priority,
        "user_id": "dost",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "tier": "pro",
            "source": "dost",
            "qwen_task_id": f"jev-exec-dost-{task_id[:8]}",
        },
        "result": None,
        "error": None,
    }
    if parent_task_id:
        task["metadata"]["parent_task_id"] = parent_task_id
        task["title"] = f"Follow-up to {parent_task_id[:8]}: {prompt[:50]}"
    if chain:
        task["metadata"]["chain"] = chain
        task["title"] = f"Chain parent: {prompt[:50]}"
    if workspace_id:
        task["metadata"]["workspace_id"] = workspace_id
    if dry_run:
        return {
            "ok": True,
            "task_id": task_id,
            "agent_id": task["agent_id"],
            "priority": priority,
            "dry_run": True,
            "message": f"[DRY RUN] Would submit prompt to fleet as task {task_id} with priority {priority}.",
            "task_preview": task,
        }
    try:
        HIVE_DIR.mkdir(parents=True, exist_ok=True)
        task_path = HIVE_DIR / f"{task_id}.json"
        task_path.write_text(json.dumps(task, indent=2))
        return {
            "ok": True,
            "task_id": task_id,
            "agent_id": task["agent_id"],
            "priority": priority,
            "message": f"Prompt submitted to fleet (task {task_id}). The dispatcher will execute it on the next cycle.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


DEBATE_SYNTHESIS_SYSTEM = """You are the dost from THE CLAUDE COMPANY synthesizing a fleet debate.

Several agents answered the SAME question independently. Read their answers below and produce a short plain-language summary:

- Open with a count line: "X of Y agree on ..." or "X of Y agree, Z disagree".
- If any agent disagrees, say why: "Z disagree because ...".
- Keep it to 2-4 sentences. No bullet lists, no internal IDs, no model names, no technical plumbing.
- Be honest: if answers are mixed or some agents errored, say so plainly.

Answers:
{answers_block}"""


def _synthesize_debate(prompt: str, answers: list[dict]) -> str:
    """Ask the LLM to synthesize agent answers into an agree/disagree summary."""
    lines = []
    for a in answers:
        if a.get("error"):
            lines.append(f"- {a['agent_id']} ({a['tier']}): ERROR — {a['error']}")
        else:
            answer = (a.get("answer") or "").strip()
            lines.append(f"- {a['agent_id']} ({a['tier']}): {answer}")
    answers_block = "\n".join(lines) if lines else "(no answers received)"

    result = chat_completion(
        [
            {"role": "system", "content": DEBATE_SYNTHESIS_SYSTEM.format(answers_block=answers_block)},
            {"role": "user", "content": f"Question: {prompt}"},
        ],
        temperature=0.3,
        max_tokens=400,
    )
    text = (result.get("text") or "").strip()
    if text:
        return text
    # Deterministic fallback when no LLM provider is available
    ok = [a for a in answers if not a.get("error") and a.get("answer")]
    if not ok:
        return f"0 of {len(answers)} agents returned an answer (all errored)."
    return (
        f"{len(ok)} of {len(answers)} agents answered. "
        f"Responding agents: {', '.join(a['agent_id'] for a in ok)}. "
        "No clear agreement/disagreement breakdown available without an LLM provider."
    )


def dispatch_debate_to_fleet(prompt: str, agents: list[str] | None = None) -> dict:
    """Fan one question out to multiple pro agents, each answering independently.

    Writes ONE task file per agent to HIVE_DIR (metadata.source="dost",
    metadata.debate_id=<shared UUID>, metadata.debate=true, agent_id=<agent>)
    AND calls the CloudModelOrchestrator directly for each agent so answers come
    from different perspectives (the dispatcher would otherwise override every
    dost task to general-assistant).

    Returns {"debate_id", "task_ids", "agents", "answers", "synthesis"}.
    Read-only: paper-only, no live orders, no dispatcher writes.
    """
    import uuid

    agent_tiers = _agent_tiers()
    if agents is None:
        agents = list(DEBATE_DEFAULT_AGENTS)
    # Preserve order, dedupe, keep only agents registered in office.json.
    known = [a for a in dict.fromkeys(agents) if a in agent_tiers]
    if not known:
        known = [a for a in agents if a in agent_tiers] or list(DEBATE_DEFAULT_AGENTS)

    # Answer cache: return cached result if question was asked recently.
    question_hash = _hash_question(prompt)
    cached = _get_cached_answer(question_hash)
    if cached:
        return {
            "debate_id": cached.get("debate_id", f"debate-cache-{question_hash}"),
            "task_ids": [],
            "agents": cached.get("agents", []),
            "answers": [
                {
                    "agent_id": a.get("agent_id", "cached"),
                    "tier": a.get("tier", "cached"),
                    "model": a.get("model"),
                    "pool": a.get("pool"),
                    "answer": cached.get("answer", ""),
                    "error": None,
                }
                for a in cached.get("agent_answers", [])
            ],
            "synthesis": cached.get("synthesis", ""),
            "_cached": True,
            "cost_units": cached.get("cost_units", 0),
        }

    debate_id = f"debate-{uuid.uuid4().hex[:8]}"
    context = build_context()
    orchestrator = CloudModelOrchestrator()

    # Cooldown pre-check: debate has its own orchestrator instance with
    # separate cooldown state from the dispatcher. Log which pools are
    # cooling down so we can avoid them / warn the user.
    pool_cooldowns = _check_pool_cooldowns()
    cooling = {p: c for p, c in pool_cooldowns.items() if c > 0}
    if cooling:
        print(
            f"[debate] pools cooling down: "
            + ", ".join(f"{p} ({c}s)" for p, c in cooling.items())
        )

    task_ids: list[str] = []
    answers: list[dict] = []

    for agent_id in known:
        tier = agent_tiers.get(agent_id, "pro")
        agent_info = {"agent_id": agent_id, "tier": tier}
        task_id = f"jev-{uuid.uuid4().hex[:8]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Direct CloudModelOrchestrator call (decide_model -> call_model),
        # same orchestration the dispatcher uses, task_type="exec".
        full_prompt = (
            f"{context}\n\n"
            f"You are the fleet agent '{agent_id}' ({tier} tier). "
            f"Answer the question independently from your own perspective. "
            f"Be direct, concise, and plain-spoken.\n\n"
            f"QUESTION: {prompt}"
        )
        answer_text = None
        model_used = None
        pool_used = None
        error = None
        # Cooldown-aware selection + auto-retry on provider failure.
        answer_text, model_used, pool_used, error = _call_with_retry(
            orchestrator,
            agent_info,
            full_prompt,
            task_id=f"debate-{debate_id}-{agent_id}",
            pool_cooldowns=pool_cooldowns,
            max_retries=2,
        )

        # Write one task file per agent to HIVE_DIR for the record.
        task = {
            "id": task_id,
            "title": f"Debate: {prompt[:60]}",
            "description": prompt,
            "status": "done" if answer_text else "error",
            "agent_id": agent_id,
            "priority": "normal",
            "user_id": "dost",
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "tier": tier,
                "source": "dost",
                "debate": True,
                "debate_id": debate_id,
                "qwen_task_id": f"jev-exec-dost-{task_id[:8]}",
            },
            "result": (
                {"text": answer_text, "model": model_used, "pool": pool_used, "source": "cloud"}
                if answer_text
                else None
            ),
            "error": error,
        }
        try:
            HIVE_DIR.mkdir(parents=True, exist_ok=True)
            (HIVE_DIR / f"{task_id}.json").write_text(json.dumps(task, indent=2))
        except Exception:
            pass

        # Cost accounting: record debate call in office_pnl.json (source="debate")
        # so it isn't a blind spot vs dispatcher tasks.
        status = "done" if answer_text else "error"
        cost_units = _cost_units_for_pool(pool_used)
        try:
            _record_debate_to_pnl(
                task_id=task_id,
                agent_id=agent_id,
                tier=tier,
                status=status,
                cost_units=cost_units,
                pool_name=pool_used,
                created_at=now,
            )
        except Exception:
            pass

        task_ids.append(task_id)
        answers.append(
            {
                "agent_id": agent_id,
                "tier": tier,
                "model": model_used,
                "pool": pool_used,
                "answer": answer_text,
                "error": error,
            }
        )

    synthesis = _synthesize_debate(prompt, answers)

    MEMORY.add_interaction(
        prompt, "debate", f"Debate {debate_id}: {len(answers)} agents ({', '.join(known)})"
    )

    # Cache the result for repeat questions (10-min TTL).
    total_cost = sum(
        _cost_units_for_pool(a.get("pool")) for a in answers if a.get("pool")
    )
    cache_payload = {
        "debate_id": debate_id,
        "agents": [
            {"agent_id": a["agent_id"], "tier": a["tier"], "model": a.get("model"), "pool": a.get("pool")}
            for a in answers
        ],
        "agent_answers": answers,
        "answer": synthesis,
        "synthesis": synthesis,
        "cost_units": total_cost,
    }
    try:
        _cache_answer(
            question_hash,
            prompt,
            synthesis,
            None,
            None,
            total_cost,
            debate_id=debate_id,
            agents=[
                {"agent_id": a["agent_id"], "tier": a["tier"], "model": a.get("model"), "pool": a.get("pool")}
                for a in answers
            ],
            agent_answers=answers,
            synthesis=synthesis,
        )
    except Exception:
        pass

    return {
        "debate_id": debate_id,
        "task_ids": task_ids,
        "agents": known,
        "answers": answers,
        "synthesis": synthesis,
    }


def dispatcher_status_line() -> str:
    """One-line fleet status for inclusion in dost context."""
    st = _fetch_dispatcher_status()
    if st is None:
        return "Fleet status: unreachable (dispatcher may be down)."
    return (
        f"Fleet: {st['tasks_done']}/{st['tasks_created']} tasks done "
        f"({st['completion_rate']:.0f}% complete), error rate {st['error_rate_total']:.1f}%, "
        f"{st['calls_today']} calls today, {st['pools_available']} provider pools available, "
        f"{st['headroom_pct']:.0f}% free-tier headroom."
    )


def list_recent_dost_tasks(limit: int = 20, status_filter: str | None = None, agent_filter: str | None = None) -> list[dict]:
    """List recent dost-submitted tasks (source == "dost") sorted by updated_at.

    Returns a list of dicts with task_id, status, result preview (first 200
    chars), model, pool, agent_id.
    """
    HIVE_DIR = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "tasks")
    tasks = []
    if not HIVE_DIR.exists():
        return tasks
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue
        if status_filter and task.get("status") != status_filter:
            continue
        if agent_filter and task.get("agent_id") != agent_filter:
            continue
        result = task.get("result") or {}
        preview = ""
        if isinstance(result, dict):
            preview = result.get("preview", "") or result.get("text", "") or ""
        elif isinstance(result, str):
            preview = result
        preview = str(preview)[:200]
        tasks.append(
            {
                "task_id": task.get("id", ""),
                "status": task.get("status", ""),
                "preview": preview,
                "model": result.get("model", "?") if isinstance(result, dict) else "?",
                "pool": result.get("pool", "?") if isinstance(result, dict) else "?",
                "agent_id": task.get("agent_id", ""),
                "updated_at": task.get("updated_at", ""),
            }
        )
    tasks.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    return tasks[:limit]


def search_history(query: str | None = None, limit: int = 10) -> list[dict]:
    """Search dost-submitted tasks by keyword, or list recent if no query.

    Matches against task title, description, and result text. Returns a list
    of dicts with task_id, status, preview, model, pool, agent_id, updated_at.
    Case-insensitive substring match. If query is None/empty, returns the most
    recent dost tasks (history paging).
    """
    HIVE_DIR = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "tasks")
    results = []
    if not HIVE_DIR.exists():
        return results
    q = query.lower() if query else None
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue
        # Build haystack from title, description, result text.
        haystack_parts = [
            task.get("title", "") or "",
            task.get("description", "") or "",
        ]
        result = task.get("result") or {}
        if isinstance(result, dict):
            haystack_parts.append(result.get("text", "") or "")
            haystack_parts.append(result.get("preview", "") or "")
        elif isinstance(result, str):
            haystack_parts.append(result)
        haystack = " ".join(haystack_parts).lower()
        if q is None or q in haystack:
            preview = ""
            if isinstance(result, dict):
                preview = result.get("preview", "") or result.get("text", "") or ""
            elif isinstance(result, str):
                preview = result
            preview = str(preview)[:200]
            results.append(
                {
                    "task_id": task.get("id", ""),
                    "status": task.get("status", ""),
                    "preview": preview,
                    "model": result.get("model", "?") if isinstance(result, dict) else "?",
                    "pool": result.get("pool", "?") if isinstance(result, dict) else "?",
                    "agent_id": task.get("agent_id", ""),
                    "updated_at": task.get("updated_at", ""),
                    "title": task.get("title", "") or "",
                    "parent_task_id": (task.get("metadata") or {}).get("parent_task_id", ""),
                }
            )
    results.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    return results[:limit]


def search_history_regex(pattern, limit: int = 10) -> list[dict]:
    """Search dost-submitted tasks by compiled regex pattern.

    Matches against task title, description, and result text using re.search.
    Returns a list of dicts with task_id, status, preview, model, pool,
    agent_id, updated_at, title, parent_task_id.
    """
    import re

    HIVE_DIR = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "tasks")
    results = []
    if not HIVE_DIR.exists():
        return results
    for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
        try:
            with open(hive_file) as f:
                task = json.load(f)
        except Exception:
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue
        # Build haystack from title, description, result text.
        haystack_parts = [
            task.get("title", "") or "",
            task.get("description", "") or "",
        ]
        result = task.get("result") or {}
        if isinstance(result, dict):
            haystack_parts.append(result.get("text", "") or "")
            haystack_parts.append(result.get("preview", "") or "")
        elif isinstance(result, str):
            haystack_parts.append(result)
        haystack = " ".join(haystack_parts)
        if pattern.search(haystack):
            preview = ""
            if isinstance(result, dict):
                preview = result.get("preview", "") or result.get("text", "") or ""
            elif isinstance(result, str):
                preview = result
            preview = str(preview)[:200]
            results.append(
                {
                    "task_id": task.get("id", ""),
                    "status": task.get("status", ""),
                    "preview": preview,
                    "model": result.get("model", "?") if isinstance(result, dict) else "?",
                    "pool": result.get("pool", "?") if isinstance(result, dict) else "?",
                    "agent_id": task.get("agent_id", ""),
                    "updated_at": task.get("updated_at", ""),
                    "title": task.get("title", "") or "",
                    "parent_task_id": (task.get("metadata") or {}).get("parent_task_id", ""),
                }
            )
    results.sort(key=lambda t: t["updated_at"] or "", reverse=True)
    return results[:limit]


AUDIT_SYSTEM = """You are Dost, talking to a close friend about the health of their computer systems.
Below is a read-only survey that just ran. Each line is one system: ok or not, and its problems.

{survey}

Summarise it in plain words:
- Start with one line: how many systems are ok out of how many.
- Then the problems, most serious first, one short line each, in everyday language.
- Only use facts from the survey. Do not invent causes or fixes.
- End by saying you only looked and changed nothing."""


def audit_reply() -> str:
    try:
        results = run_system_audit()
    except Exception as e:
        return f"I tried to audit the system but the check itself failed ({type(e).__name__}: {str(e)[:120]}). I changed nothing."
    ok = sum(1 for r in results if r.get("ok"))
    lines = []
    for r in results:
        status = "OK" if r.get("ok") else "PROBLEM"
        probs = "; ".join(r.get("problems") or []) or r.get("summary", "")
        lines.append(f"- {r.get('name')}: {status}. {probs}")
    survey = "\n".join(lines)
    MEMORY.add_interaction("system audit", "ops", f"Audit: {ok}/{len(results)} ok")
    result = chat_completion(
        [{"role": "system", "content": AUDIT_SYSTEM.format(survey=survey)},
         {"role": "user", "content": "How is my system doing?"}],
        temperature=0.2, max_tokens=500,
    )
    text = (result.get("text") or "").strip()
    if text:
        return text
    return f"{ok} of {len(results)} systems are OK.\n" + survey + "\nI only looked; I changed nothing."


def _asked_for_command(task: str, command: str) -> bool:
    """Only run a pipeline command when the person clearly named it."""
    t = task.lower()
    if command == "all":
        return "run all" in t or "full pipeline" in t or "whole pipeline" in t
    return command in t


def companion_respond(task: str) -> str:
    """Pet-style reply: no greeting or boilerplate, shorter and warmer. Same routing as dost_respond."""
    if wants_audit(task):
        return audit_reply()
    context = build_context()

    # Surface critical alerts proactively so the pet never hides a problem.
    try:
        from ops.proactive_monitor import check_fleet_health
        live_alerts = check_fleet_health()
        critical = [a for a in live_alerts if a.get("severity") == "critical"]
        alert_prefix = ""
        if critical:
            alert_prefix = "⚠️ " + "; ".join(a.get("message", "")[:80] for a in critical[:3]) + ". "
    except Exception:  # pragma: no cover - defensive
        alert_prefix = ""

    decision = llm_decide(task, context, style=COMPANION_STYLE)

    if decision and decision.startswith("COMMAND:"):
        command = decision[len("COMMAND:"):].strip()
        if command not in RESEARCH_COMMANDS or not _asked_for_command(task, command):
            # The model wanted to run something the person did not ask for. Reply in words instead.
            decision = llm_decide(task, context, style=COMPANION_STYLE +
                                  "\n- Do NOT reply with COMMAND. Answer in plain words.")
            if decision and decision.startswith("COMMAND:"):
                decision = ""
        if decision.startswith("COMMAND:") and command in RESEARCH_COMMANDS:
            output = run_research_command(command)
            MEMORY.add_interaction(task, "research", f"Executed research command: {command}")
            narration = llm_narrate(command, output, context)
            return narration or fallback_narrate(command, output)

    if decision and not decision.startswith("COMMAND:"):
        MEMORY.add_interaction(task, route_department(task), "Conversational response")
        return alert_prefix + decision

    response = fallback_converse(task, context)
    MEMORY.add_interaction(task, route_department(task), "Conversational response (fallback)")
    return alert_prefix + response


def generate_daily_briefing():
    lines = [
        f"Good morning, {MEMORY.profile['name']}. Here's your daily briefing from THE CLAUDE COMPANY:",
        "",
    ]

    research_dir = (Path.home() / "Documents" / "indian-paper-trading")
    queue_dir = research_dir / "results" / "hypothesis_queue"
    if queue_dir.exists():
        hyps = list(queue_dir.glob("*.json"))
        passed = sum(1 for p in hyps if json.loads(p.read_text()).get("status") == "passed")
        failed = sum(1 for p in hyps if json.loads(p.read_text()).get("status") == "failed")
        lines.append(f"📊 Research: {len(hyps)} hypotheses tracked ({passed} passed, {failed} failed).")
        lines.append("   Key finding: No viable edge at ₹1 lakh + free data. The bull put + IV rank ≥80% "
                     "strategy made +₹762 in tuning but lost -₹5,330 in out-of-sample testing — so we retired it.")
    else:
        lines.append("📊 Research: No hypotheses registered yet.")

    lines.append("")
    lines.append("🤖 Fleet: 32 agents running. All paper-only. Kill switch locked.")
    lines.append("💰 Trading: Paper only. No live orders — ever.")
    lines.append("⚙️ Upgrade: Run 'python company.py upgrade --test' to verify the codebase.")
    lines.append("")
    lines.append("⚠️  Reminder: I can research and paper-trade, but I cannot execute live orders. That's by design.")
    lines.append("")
    lines.append("What would you like to focus on today?")

    briefing = "\n".join(lines)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (DOST_BRIEFINGS / f"{today}.txt").write_text(briefing)
    return briefing


def _push_telegram_briefing() -> None:
    """Generate the daily briefing and push it to Telegram (owner chat only)."""
    import subprocess
    from pathlib import Path

    # Read bot token
    env = {}
    try:
        for line in (Path.home() / ".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set in ~/.env — cannot push briefing.")
        return

    # Read allowlist for owner chat_id
    allowlist_file = Path.home() / ".openclaw" / "telegram_allowlist.json"
    try:
        allowlist = json.loads(allowlist_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        allowlist = []
    if not allowlist:
        print("No Telegram allowlist (owner chat) yet — start a chat with the bot first.")
        return
    chat_id = allowlist[0]

    briefing = generate_daily_briefing()

    # Dedupe: don't re-send today's briefing if already sent
    sent_file = DOST_BRIEFINGS / ".last_sent"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if sent_file.exists() and sent_file.read_text().strip() == today:
        print("Briefing already sent today.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    proc = subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"chat_id": chat_id, "text": briefing, "parse_mode": "Markdown"}),
         "--max-time", "30"],
        capture_output=True, text=True, timeout=40,
    )
    try:
        result = json.loads(proc.stdout)
        if result.get("ok"):
            sent_file.write_text(today)
            print("Briefing pushed to Telegram.")
        else:
            print(f"Telegram push failed: {proc.stdout[:300]}")
    except json.JSONDecodeError:
        print(f"Telegram push failed (non-JSON): {proc.stdout[:300]}")


LAUNCHCTL_LABELS = {
    "dispatcher": "dev.krisharyanagarwal.jev-dispatcher",
    "memory learner": "dev.krisharyanagarwal.dost-memory-learner",
    "morning digest": "dev.krisharyanagarwal.dost-morning-digest",
}


def _plists_loaded() -> tuple:
    """Return (ok, detail) for whether the dost launchd plists are loaded."""
    try:
        out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10
        ).stdout
        loaded = {line.split()[-1] for line in out.splitlines() if line.strip()}
        missing = [name for name, label in LAUNCHCTL_LABELS.items() if label not in loaded]
        if missing:
            return False, "not loaded: " + ", ".join(missing)
        return True, "all loaded"
    except Exception as e:
        return False, f"launchctl check failed ({e})"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def doctor() -> tuple:
    """One-command system health check.

    Returns (board_text, exit_code). Exit code 0 if all checks pass, 1 if any
    fail. Read-only — changes nothing.
    """
    checks = []

    # 1. Dispatcher reachable + PID alive
    st = _fetch_dispatcher_status()
    reachable = st is not None
    pid_text = "unknown"
    pid_ok = False
    try:
        pid_text = (Path.home() / ".openclaw" / "jev-dispatcher.pid").read_text().strip()
        pid_ok = _pid_alive(int(pid_text))
    except Exception:
        pid_ok = False
    dispatcher_ok = reachable and pid_ok
    checks.append(
        ("Dispatcher reachable + PID alive",
         dispatcher_ok,
         f"reachable={reachable} pid={pid_text} alive={pid_ok}")
    )

    # 2. Metrics fresh (<10 min) — dispatcher log updated within 10 min
    log_path = (Path.home() / ".openclaw" / "jev-dispatcher.log")
    fresh = False
    age_text = "unknown"
    try:
        mtime = log_path.stat().st_mtime
        age_sec = time.time() - mtime
        fresh = reachable and age_sec < 600
        age_text = f"{age_sec:.0f}s"
    except Exception:
        fresh = False
    checks.append(("Metrics fresh (<10 min)", fresh,
                   f"reachable={reachable} log age={age_text}"))

    # 3. office.json valid
    office_ok = False
    try:
        json.loads(
            (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "config" / "office.json").read_text()
        )
        office_ok = True
    except Exception:
        pass
    checks.append(("office.json valid", office_ok, ""))

    # 4. Plists loaded (dispatcher, memory learner, morning digest)
    plists_ok, plists_detail = _plists_loaded()
    checks.append(
        ("Plists loaded (dispatcher, memory learner, morning digest)", plists_ok, plists_detail)
    )

    # 5. qwen_local / ollama reachable
    ollama_ok = False
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=4)
        ollama_ok = True
    except Exception:
        pass
    checks.append(("qwen_local / ollama reachable", ollama_ok, "http://127.0.0.1:11434/api/tags"))

    # 6. Git status clean-ish (untracked files OK, tracked changes not OK)
    git_clean = True
    git_detail = ""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10,
            cwd=str(COMPANY_DIR),
        ).stdout
        tracked_changes = [line for line in out.splitlines() if line and not line.startswith("?? ")]
        if tracked_changes:
            git_clean = False
            git_detail = "tracked changes: " + "; ".join(tracked_changes[:5])
    except Exception as e:
        git_clean = False
        git_detail = f"git check failed ({e})"
    checks.append(("Git status clean-ish", git_clean, git_detail))

    # 7. No .git/index.lock
    index_lock = COMPANY_DIR / ".git" / "index.lock"
    no_lock = not index_lock.exists()
    checks.append(("No .git/index.lock", no_lock, str(index_lock)))

    # 8. Provider-health audit — dispatcher metrics plus a direct probe of the
    #    local pools, so a dead local server can never be reported as up.
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
            metrics = json.loads(r.read().decode("utf-8"))
        pools = metrics.get("provider_pools", {})
        pools_ok, pool_detail = summarize_provider_pools(pools, probe_local_pools())
    except Exception as e:
        pools_ok = False
        pool_detail = f"metrics unreachable ({e})"
    checks.append(("Provider pools healthy", pools_ok, pool_detail))

    # 9. Anomaly alerts — error rate > 5%, pool down > 10 min, findings pending > 30 days.
    anomaly_ok = True
    anomaly_parts = []
    try:
        st = _fetch_dispatcher_status()
        if st:
            er = st.get("error_rate_total", 0)
            if er > 5.0:
                anomaly_ok = False
                anomaly_parts.append(f"error rate {er:.1f}% (>5%)")
        # Re-fetch metrics for pool cooldown detail
        try:
            with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
                m2 = json.loads(r.read().decode("utf-8"))
            p2 = m2.get("provider_pools", {})
            for pname, pinfo in p2.items():
                cd = pinfo.get("cooldown_remaining", 0)
                if cd > 600:  # > 10 min
                    anomaly_ok = False
                    anomaly_parts.append(f"{pname} cooling {cd//60}min")
        except Exception:
            pass
        # Findings pending > 30 days
        store = _load_findings_store()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stale_pending = 0
        for f in store.get("findings", []):
            if f.get("verification_status") == "pending":
                date_str = f.get("date", "")
                if date_str:
                    try:
                        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if d < cutoff:
                            stale_pending += 1
                    except Exception:
                        pass
        if stale_pending > 0:
            anomaly_ok = False
            anomaly_parts.append(f"{stale_pending} findings pending >30 days")
    except Exception as e:
        anomaly_ok = False
        anomaly_parts.append(f"anomaly check failed ({e})")
    anomaly_detail = "; ".join(anomaly_parts) if anomaly_parts else "all clear"
    checks.append(("Anomaly alerts", anomaly_ok, anomaly_detail))

    # 10. Quota burn projection — when will free-tier ceiling be hit?
    quota_ok = True
    quota_detail = "unknown"
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
            m3 = json.loads(r.read().decode("utf-8"))
        fc = m3.get("free_ceiling", {})
        ceiling = fc.get("calls_per_day_ceiling", 0)
        calls_today = fc.get("calls_today", 0)
        headroom_pct = fc.get("headroom_pct", 100)
        if ceiling > 0:
            burn_rate = calls_today / max(1, datetime.now().hour)  # calls per hour so far
            hours_to_ceiling = (ceiling - calls_today) / max(burn_rate, 1)
            quota_detail = f"{calls_today}/{ceiling} calls ({headroom_pct:.0f}% headroom), ~{hours_to_ceiling:.0f}h to ceiling at current burn"
            if headroom_pct < 20:
                quota_ok = False
                quota_detail += " — LOW HEADROOM"
        else:
            quota_detail = "no ceiling data"
    except Exception as e:
        quota_ok = False
        quota_detail = f"quota check failed ({e})"
    checks.append(("Quota burn projection", quota_ok, quota_detail))

    # 11. Daily cost cap — advisory only; never halts dispatch.
    cost_cap_ok, cost_cap_detail = _daily_cost_check(
        (Path.home() / ".openclaw" / "office_pnl.json")
    )
    checks.append(("Daily cost cap", cost_cap_ok, cost_cap_detail))

    # 12. Alert webhook — POST anomalies to configured webhook URL.
    webhook_ok = True
    webhook_detail = "no URL configured"
    try:
        if ALERT_WEBHOOK_URL:
            # Fire and forget — don't block the health check.
            import threading

            def _post_webhook():
                try:
                    payload = json.dumps(
                        {
                            "check": "dost-doctor",
                            "status": "fail" if not all_pass else "pass",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "checks": [
                                {"name": name, "ok": ok, "detail": detail}
                                for name, ok, detail in checks
                                if not ok
                            ],
                        }
                    ).encode()
                    req = urllib.request.Request(
                        ALERT_WEBHOOK_URL,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status >= 400:
                            webhook_ok = False
                            webhook_detail = f"webhook returned {resp.status}"
                except Exception as e:
                    webhook_ok = False
                    webhook_detail = f"webhook failed ({e})"

            threading.Thread(target=_post_webhook, daemon=True).start()
            webhook_detail = "configured, firing async"
        else:
            webhook_detail = "no ALERT_WEBHOOK_URL set"
    except Exception as e:
        webhook_ok = False
        webhook_detail = f"webhook setup failed ({e})"
    checks.append(("Alert webhook", webhook_ok, webhook_detail))

    # 13. Cost anomaly detection — today's cost vs 7-day average.
    cost_anomaly_ok = True
    cost_anomaly_detail = "unknown"
    try:
        pnl_path = (Path.home() / ".openclaw" / "office_pnl.json")
        if pnl_path.exists():
            pnl = json.loads(pnl_path.read_text())
            if isinstance(pnl, list) and len(pnl) > 1:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                today_cost = sum(
                    t.get("cost_units", 0)
                    for t in pnl
                    if t.get("created_at", "").startswith(today)
                )
                # 7-day average excluding today
                past_costs = []
                for i in range(2, 8):
                    day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime(
                        "%Y-%m-%d"
                    )
                    day_cost = sum(
                        t.get("cost_units", 0)
                        for t in pnl
                        if t.get("created_at", "").startswith(day)
                    )
                    past_costs.append(day_cost)
                avg_cost = sum(past_costs) / max(1, len(past_costs))
                cost_anomaly_detail = f"Today: {today_cost}, 7-day avg: {avg_cost:.1f}"
                if today_cost > avg_cost * 1.5 and today_cost > 20:
                    cost_anomaly_ok = False
                    cost_anomaly_detail += " — SPIKE DETECTED"
                elif today_cost > avg_cost * 1.2 and today_cost > 20:
                    cost_anomaly_detail += " — elevated"
                else:
                    cost_anomaly_detail += " — normal"
            else:
                cost_anomaly_detail = "insufficient history"
        else:
            cost_anomaly_detail = "no P&L file"
    except Exception as e:
        cost_anomaly_ok = False
        cost_anomaly_detail = f"cost anomaly check failed ({e})"
    checks.append(("Cost anomaly", cost_anomaly_ok, cost_anomaly_detail))

    # 14. Finding expiry reminder — pending findings > 7 days.
    finding_expiry_ok = True
    finding_expiry_detail = "unknown"
    try:
        store = _load_findings_store()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        stale = []
        for f in store.get("findings", []):
            if f.get("verification_status") == "pending":
                date_str = f.get("date", "")
                if date_str:
                    try:
                        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if d < cutoff:
                            stale.append(
                                f"{f.get('agent', '?')}: {f.get('claim', '')[:50]}"
                            )
                    except Exception:
                        pass
        if stale:
            finding_expiry_ok = False
            finding_expiry_detail = f"{len(stale)} stale: " + "; ".join(stale[:3])
            if len(stale) > 3:
                finding_expiry_detail += f" (+{len(stale) - 3} more)"
        else:
            finding_expiry_detail = "none stale"
    except Exception as e:
        finding_expiry_ok = False
        finding_expiry_detail = f"finding expiry check failed ({e})"
    checks.append(("Finding expiry", finding_expiry_ok, finding_expiry_detail))

    # Build board
    all_pass = all(ok for _, ok, _ in checks)
    lines = [
        "╔═════════════════════════════════════════════════════════════════╗",
        "║  dost --doctor — system health check                          ║",
        "╚═════════════════════════════════════════════════════════════════╝",
        "",
    ]
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        lines.append(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    lines.append("")
    if all_pass:
        lines.append("All checks passed.")
        code = 0
    else:
        lines.append("One or more checks FAILED.")
        code = 1
    return "\n".join(lines), code


def export_results(fmt: str = "json") -> str:
    """Export the most recent debate and dispatch results to a file.

    Reads the latest dost task with metadata.debate=true and the latest
    dost task without debate, writes them to dost/exports/.
    Returns the file path.
    """
    from pathlib import Path
    export_dir = DOST_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    HIVE_DIR = (Path(__file__).resolve().parents[1] / "packages" / "office-os" / "tasks")
    latest_debate = None
    latest_dispatch = None
    if HIVE_DIR.exists():
        for hive_file in sorted(HIVE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                task = json.loads(hive_file.read_text())
            except Exception:
                continue
            if (task.get("metadata") or {}).get("source") != "dost":
                continue
            md = task.get("metadata") or {}
            if md.get("debate") and latest_debate is None:
                latest_debate = task
            elif not md.get("debate") and latest_dispatch is None:
                latest_dispatch = task
            if latest_debate and latest_dispatch:
                break

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "debate": latest_debate,
        "dispatch": latest_dispatch,
    }
    if fmt == "md":
        lines = [f"# Dost Export — {data['exported_at']}", ""]
        if latest_debate:
            lines.append("## Latest Debate")
            lines.append(f"- Question: {latest_debate.get('description', '')}")
            lines.append(f"- Agent: {latest_debate.get('agent_id', '')}")
            lines.append(f"- Status: {latest_debate.get('status', '')}")
            r = latest_debate.get("result") or {}
            if isinstance(r, dict) and r.get("text"):
                lines.append(f"- Answer: {r['text'][:500]}")
            lines.append("")
        if latest_dispatch:
            lines.append("## Latest Dispatch")
            lines.append(f"- Prompt: {latest_dispatch.get('description', '')}")
            lines.append(f"- Agent: {latest_dispatch.get('agent_id', '')}")
            lines.append(f"- Status: {latest_dispatch.get('status', '')}")
            r = latest_dispatch.get("result") or {}
            if isinstance(r, dict) and r.get("text"):
                lines.append(f"- Answer: {r['text'][:500]}")
        content = "\n".join(lines)
        ext = "md"
    else:
        content = json.dumps(data, indent=2)
        ext = "json"
    out_path = export_dir / f"dost_export_{timestamp}.{ext}"
    out_path.write_text(content)
    return str(out_path)


def synthesis_detail() -> str:
    """Detailed synthesis report over all findings.

    Groups findings by agent, counts verification statuses, shows
    contested/pending items with their claims for Tier C review.
    """
    store = _load_findings_store()
    findings = store.get("findings", [])

    by_agent = {}
    vs_counts = {}
    for f in findings:
        agent = f.get("agent", "unknown")
        vs = f.get("verification_status", "missing")
        by_agent.setdefault(agent, []).append(f)
        vs_counts[vs] = vs_counts.get(vs, 0) + 1

    lines = [
        "# Synthesis Detail — Findings Review",
        f"Total findings: {len(findings)}",
        "",
        "## Verification Status",
    ]
    for vs, count in sorted(vs_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {vs}: {count}")
    lines.append("")

    # Contested and needs-review items are most important for Tier C
    priority = ["contested", "needs-review", "pending"]
    lines.append("## Tier C Review — Priority Items")
    for vs in priority:
        items = [f for f in findings if f.get("verification_status") == vs]
        if not items:
            continue
        lines.append(f"\n### {vs} ({len(items)})")
        for f in items[:10]:  # cap at 10 per status
            claim = (f.get("claim") or "")[:100]
            lines.append(f"- [{f.get('agent', '?')}] {claim}... ({f.get('date', '?')[:10]})")

    lines.append("")
    lines.append("## By Agent")
    for agent, items in sorted(by_agent.items(), key=lambda x: -len(x[1])):
        vs_for_agent = {}
        for f in items:
            v = f.get("verification_status", "missing")
            vs_for_agent[v] = vs_for_agent.get(v, 0) + 1
        detail = ", ".join(f"{k}={v}" for k, v in sorted(vs_for_agent.items()))
        lines.append(f"- {agent}: {len(items)} findings ({detail})")

    return "\n".join(lines)


# --- Automation -------------------------------------------------------------
# Auto-archive old findings and weekly digest for Tier C review.

def auto_archive_findings(store: dict | None = None, days: int = 30) -> int:
    """Auto-archive pending findings older than `days` days.

    Sets verification_status to 'archived' for pending findings whose date
    is older than the cutoff. Does NOT delete — Tier C can still review.
    Returns the number of findings archived.
    """
    if store is None:
        store = _load_findings_store()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    archived = 0
    for f in store.get("findings", []):
        if f.get("verification_status") != "pending":
            continue
        date_str = f.get("date", "")
        if not date_str:
            continue
        try:
            d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if d < cutoff:
                f["verification_status"] = "archived"
                f["archived_at"] = datetime.now(timezone.utc).isoformat()
                archived += 1
        except Exception:
            pass
    if archived > 0:
        _save_findings_store(store)
    return archived


def weekly_findings_digest() -> str:
    """Weekly digest: new findings since last week, grouped by verification status."""
    store = _load_findings_store()
    findings = store.get("findings", [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    new_findings = []
    for f in findings:
        date_str = f.get("date", "")
        if not date_str:
            continue
        try:
            d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if d >= cutoff:
                new_findings.append(f)
        except Exception:
            pass

    vs_counts = {}
    for f in new_findings:
        v = f.get("verification_status", "missing")
        vs_counts[v] = vs_counts.get(v, 0) + 1

    lines = [
        "# Weekly Findings Digest",
        f"Week ending {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"New findings: {len(new_findings)}",
        "",
    ]
    for vs, count in sorted(vs_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {vs}: {count}")
    lines.append("")
    if new_findings:
        lines.append("## New Claims")
        for f in new_findings[:15]:
            claim = (f.get("claim") or "")[:100]
            lines.append(f"- [{f.get('agent', '?')}] {claim}... ({f.get('date', '?')[:10]})")
    else:
        lines.append("No new findings this week.")
    return "\n".join(lines)


def load_template(name: str) -> dict | None:
    """Load a task template from dost/templates/<name>.json.

    Template format:
    {
        "prompt": "What is the fleet completion rate?",
        "agent_id": "strategy-advisor",
        "priority": "normal"
    }
    """
    template_path = DOST_TEMPLATES / f"{name}.json"
    if not template_path.exists():
        # Also try without .json extension
        template_path = DOST_TEMPLATES / name
        if not template_path.exists():
            return None
    try:
        return json.loads(template_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _handle_workspace_command(args) -> None:
    """Handle the `dost workspace` subcommand group."""
    action = args.action
    rest = args.rest
    if action == "list":
        workspaces = list_workspaces()
        if not workspaces:
            print("No workspaces found.")
        else:
            print("ID | Name | Plan | Owner | Active")
            for ws in workspaces:
                print(
                    f"{ws['id']} | {ws.get('name','')} | {ws.get('plan','')} | "
                    f"{ws.get('owner_email','')} | {ws.get('active', True)}"
                )
    elif action == "create":
        if not rest:
            print("Usage: dost workspace create <name> [--owner <email>] [--plan <plan>]")
            return
        name = rest[0]
        owner = "admin@default.local"
        plan = "starter"
        i = 1
        while i < len(rest):
            if rest[i] == "--owner" and i + 1 < len(rest):
                owner = rest[i + 1]
                i += 2
            elif rest[i] == "--plan" and i + 1 < len(rest):
                plan = rest[i + 1]
                i += 2
            else:
                i += 1
        ws = create_workspace(name, owner_email=owner, plan=plan)
        print(json.dumps(ws, indent=2))
    elif action == "add-user":
        if len(rest) < 2:
            print("Usage: dost workspace add-user <workspace_id> <email> [role]")
            return
        workspace_id = rest[0]
        email = rest[1]
        role = rest[2] if len(rest) > 2 else "viewer"
        added = add_user(workspace_id, email, role)
        print(json.dumps(added, indent=2))
    else:
        print("Unknown workspace action. Use: list | create <name> | add-user <workspace_id> <email> [role]")


def main():
    import argparse
    import sys as _sys

    # Route `dost workspace <action> ...` through a dedicated subparser so the
    # `message` positional (nargs="?") does not steal the subcommand name.
    if len(_sys.argv) > 1 and _sys.argv[1] == "workspace":
        _ws_parser = argparse.ArgumentParser(prog="dost workspace")
        _ws_parser.add_argument("action", choices=["list", "create", "add-user"],
                                help="Workspace action: list | create <name> | add-user <workspace_id> <email> [role]")
        _ws_parser.add_argument("rest", nargs="*", help="Additional arguments for the workspace action")
        _ws_args, _ws_extras = _ws_parser.parse_known_args(_sys.argv[2:])
        _ws_args.rest = list(_ws_args.rest) + list(_ws_extras)
        _handle_workspace_command(_ws_args)
        return

    parser = argparse.ArgumentParser(description="THE CLAUDE COMPANY — Dost")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--department", choices=["research", "trading", "fleet", "ops", "upgrade", "assistant"])
    parser.add_argument("--briefing", action="store_true")
    parser.add_argument("--push-telegram", action="store_true",
                        help="Generate daily briefing and push to Telegram")
    parser.add_argument("--status", action="store_true",
                        help="Show live fleet status from dispatcher metrics")
    parser.add_argument("--results", action="store_true",
                        help="List recent dost-submitted tasks from the fleet hive")
    parser.add_argument("--history", nargs="?", const="",
                        help="Search dost task history by keyword (optional search term)")
    parser.add_argument("--dispatch", nargs="?", const="",
                        help="Submit a prompt to the fleet orchestrator (optional prompt text)")
    parser.add_argument("--debate", nargs="?", const="",
                        help="Debate mode: fan a question to multiple pro agents and synthesize")
    parser.add_argument("--template", nargs="?", const="",
                        help="Task template: load saved prompt from dost/templates/<name>.json")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--health", action="store_true", help="Check OpenAI component availability")
    parser.add_argument("--doctor", action="store_true",
                        help="Run a one-command system health check")
    parser.add_argument("--workspace", help="Workspace id to scope all dispatch operations to")
    parser.add_argument("--create-workspace", metavar="NAME",
                        help="Create a new workspace with the given name")
    parser.add_argument("--list-workspaces", action="store_true",
                        help="List all workspaces")
    parser.add_argument("--add-user", nargs=2, metavar=("EMAIL", "ROLE"),
                        help="Add a user (email role) to the current/default workspace")

    # `dost workspace` subcommand group for workspace management
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")
    ws_parser = subparsers.add_parser("workspace", help="Workspace management")
    ws_parser.add_argument("action", choices=["list", "create", "add-user"],
                           help="Workspace action: list | create <name> | add-user <workspace_id> <email> [role]")
    ws_parser.add_argument("rest", nargs="*", help="Additional arguments for the workspace action")

    args = parser.parse_args()

    if args.doctor:
        board, code = doctor()
        print(board)
        sys.exit(code)
    if args.push_telegram:
        _push_telegram_briefing()
    elif args.command == "workspace":
        _handle_workspace_command(args)
    elif args.briefing:
        print(generate_daily_briefing())
    elif args.status:
        st = _fetch_dispatcher_status()
        if st:
            print(json.dumps(st, indent=2))
        else:
            print("Fleet status: unreachable (dispatcher may be down).")
    elif args.results:
        tasks = list_recent_dost_tasks()
        if not tasks:
            print("No dost-submitted tasks found.")
        else:
            for t in tasks:
                print(
                    f"{t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['model']} | {t['pool']} | {t['updated_at']}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.history is not None:
        query = args.history if args.history else input("Search history for: ")
        results = search_history(query)
        if not results:
            print(f"No dost tasks matching '{query}'.")
        else:
            print(f"Found {len(results)} dost task(s) matching '{query}':")
            for t in results:
                print(
                    f"{t['task_id']} | {t['status']} | {t['agent_id']} | "
                    f"{t['model']} | {t['pool']} | {t['updated_at']}"
                )
                if t["preview"]:
                    print(f"    preview: {t['preview']}")
    elif args.create_workspace:
        ws = create_workspace(args.create_workspace, owner_email="admin@default.local")
        print(json.dumps(ws, indent=2))
    elif args.list_workspaces:
        workspaces = list_workspaces()
        if not workspaces:
            print("No workspaces found.")
        else:
            print("ID | Name | Plan | Owner")
            for ws in workspaces:
                print(f"{ws['id']} | {ws.get('name','')} | {ws.get('plan','')} | {ws.get('owner_email','')}")
    elif args.add_user:
        email, role = args.add_user
        ws_id = args.workspace or ensure_default_workspace()
        added = add_user(ws_id, email, role)
        print(json.dumps(added, indent=2))
    elif args.dispatch is not None:
        workspace_id = args.workspace or ensure_default_workspace()
        prompt = args.dispatch if args.dispatch else input("Prompt to send to fleet: ")
        result = dispatch_prompt_to_fleet(prompt, workspace_id=workspace_id)
        print(json.dumps(result, indent=2))
    elif args.debate is not None:
        prompt = args.debate if args.debate else input("Debate question: ")
        result = dispatch_debate_to_fleet(prompt)
        print(json.dumps(result, indent=2))
    elif args.template is not None:
        template_name = args.template if args.template else input("Template name: ")
        template = load_template(template_name)
        if not template:
            print(f"No template found: {template_name}")
        else:
            prompt = template.get("prompt", "")
            agent_id = template.get("agent_id")
            priority = template.get("priority", "normal")
            workspace_id = args.workspace or ensure_default_workspace()
            result = dispatch_prompt_to_fleet(prompt, agent_id=agent_id, priority=priority, workspace_id=workspace_id)
            print(json.dumps(result, indent=2))
    elif args.memory:
        print(json.dumps(MEMORY.profile, indent=2))
    elif args.context:
        print(build_context())
    elif args.health:
        print(json.dumps(provider_health(), indent=2))
    elif args.message:
        print(dost_respond(args.message, args.department))
    else:
        print(dost_greeting())
        print("\nI'm your dost. Tell me what you need: research, trading, code, writing, strategy.")
        print("Commands: --briefing, --push-telegram, --status, --dispatch, --results, --history, --memory, --context, --health, --doctor, --department X")


if __name__ == "__main__":
    main()
