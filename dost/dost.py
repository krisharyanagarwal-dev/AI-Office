#!/usr/bin/env python3
"""THE CLAUDE COMPANY — Dost Interface.

Personal AI chief of staff. Natural language in, natural language out.
The LLM generates warm, dynamic responses grounded in live company data.
Numbers are injected verbatim from files; the LLM only narrates.

Paper only. Kill switch locked. No live orders ever.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COMPANY_DIR = Path(__file__).resolve().parent.parent
DOST_DIR = Path(__file__).resolve().parent
DOST_MEMORY = DOST_DIR / "memory.json"
DOST_HISTORY = DOST_DIR / "history.jsonl"
DOST_BRIEFINGS = DOST_DIR / "briefings"
DOST_DIR.mkdir(parents=True, exist_ok=True)
DOST_BRIEFINGS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(COMPANY_DIR))
sys.path.insert(0, str(DOST_DIR))
from company_dispatcher import dispatch, route_department  # noqa: E402
from openai_components import chat_completion, provider_health  # noqa: E402
from context_builder import build_context  # noqa: E402

RESEARCH_DIR = Path("/Users/aryanagarwal/Documents/indian-paper-trading")
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
                return f"{dost_greeting()}\n\n{narration}\n\nWhat would you like to do next?"
            # Fallback narration
            return f"{dost_greeting()}\n\n{fallback_narrate(command, output)}"

    # Not a command — have the LLM write a warm conversational response
    if decision and not decision.startswith("COMMAND:"):
        # LLM already gave us a natural response
        MEMORY.add_interaction(task, route_department(task), "Conversational response")
        return f"{dost_greeting()}\n\n{decision}\n\nIs there anything else I can help you with?"

    # Fallback: no LLM available or decision unparseable
    fb = fallback_decide(task, context)
    if fb and fb.startswith("COMMAND:"):
        command = fb[len("COMMAND:"):].strip()
        output = run_research_command(command)
        MEMORY.add_interaction(task, "research", f"Executed research command: {command} (fallback)")
        return f"{dost_greeting()}\n\n{fallback_narrate(command, output)}"

    response = fallback_converse(task, context)
    MEMORY.add_interaction(task, route_department(task), "Conversational response (fallback)")
    return f"{dost_greeting()}\n\n{response}\n\nIs there anything else I can help you with?"


COMPANION_STYLE = """Talk like a close, warm friend who also happens to run the research team.
- Keep replies short: 2-4 sentences, unless the person asks for detail.
- Match their language and energy. A casual "hi" gets a casual reply.
- Use their name now and then, not every line.
- No bullet lists, headings or sign-offs unless they ask for them.
- Never end with "anything else I can help with" or similar.
- Be honest about losses and failures, but kind about it.
- Ground any numbers in the CONTEXT and never invent them.

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
  Never claim you are "going live" beyond the fleet connection."""

DISPATCHER_METRICS_URL = "http://127.0.0.1:8083/metrics"
HIVE_DIR = Path("/Users/aryanagarwal/AI-Office/packages/office-os/tasks")


def wants_audit(task: str) -> bool:
    t = task.lower()
    return any(w in t for w in AUDIT_WORDS)


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


def dispatch_prompt_to_fleet(prompt: str, agent_id: str | None = None) -> dict:
    """Submit a prompt to the fleet orchestrator by writing a task file.

    The dispatcher picks up pending task files from HIVE_DIR on each cycle
    and executes them through the cloud orchestrator. Returns the task info.
    Read-only data write — no live orders, no trading execution.
    """
    import uuid

    task_id = f"jev-{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "title": f"Dost prompt: {prompt[:60]}",
        "description": prompt,
        "status": "pending",
        "agent_id": agent_id or "strategy-advisor",
        "priority": "normal",
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
    try:
        HIVE_DIR.mkdir(parents=True, exist_ok=True)
        task_path = HIVE_DIR / f"{task_id}.json"
        task_path.write_text(json.dumps(task, indent=2))
        return {
            "ok": True,
            "task_id": task_id,
            "agent_id": task["agent_id"],
            "message": f"Prompt submitted to fleet (task {task_id}). The dispatcher will execute it on the next cycle.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
        return decision

    response = fallback_converse(task, context)
    MEMORY.add_interaction(task, route_department(task), "Conversational response (fallback)")
    return response


def generate_daily_briefing():
    lines = [
        f"Good morning, {MEMORY.profile['name']}. Here's your daily briefing from THE CLAUDE COMPANY:",
        "",
    ]

    research_dir = Path("/Users/aryanagarwal/Documents/indian-paper-trading")
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="THE CLAUDE COMPANY — Dost")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--department", choices=["research", "trading", "fleet", "ops", "upgrade", "assistant"])
    parser.add_argument("--briefing", action="store_true")
    parser.add_argument("--push-telegram", action="store_true",
                        help="Generate daily briefing and push to Telegram")
    parser.add_argument("--status", action="store_true",
                        help="Show live fleet status from dispatcher metrics")
    parser.add_argument("--dispatch", nargs="?", const="",
                        help="Submit a prompt to the fleet orchestrator (optional prompt text)")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--health", action="store_true", help="Check OpenAI component availability")
    args = parser.parse_args()

    if args.push_telegram:
        _push_telegram_briefing()
    elif args.briefing:
        print(generate_daily_briefing())
    elif args.status:
        st = _fetch_dispatcher_status()
        if st:
            print(json.dumps(st, indent=2))
        else:
            print("Fleet status: unreachable (dispatcher may be down).")
    elif args.dispatch is not None:
        prompt = args.dispatch if args.dispatch else input("Prompt to send to fleet: ")
        result = dispatch_prompt_to_fleet(prompt)
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
        print("Commands: --briefing, --push-telegram, --status, --dispatch, --memory, --context, --health, --department X")


if __name__ == "__main__":
    main()
