"""
Jarvis layer for THE CLAUDE COMPANY Dost.

Router + tools. Read-only tools run unattended; action tools (fleet dispatch)
require an explicit "yes" before writing anything. The model never gets shell
or file access: the router decides, the model only narrates.

Wire in:

    from jarvis import route, execute, build_context_packet

    call = route(user_text)
    if call:
        reply = execute(call, confirmed=...)   # read tools run at once
    else:
        reply = companion_respond(user_text)   # unchanged behaviour

Set DOST_JARVIS=1 in the environment to enable in pet_server.py.
Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dost import MEMORY, build_context
from company_dispatcher import route_department
from proactive_monitor import run_monitor_once, check_fleet_health
from persistent_memory import conversation_memory

try:  # list_recent_dost_tasks lives in dost.py
    from dost import list_recent_dost_tasks
except ImportError:  # pragma: no cover - older dost.py without it
    def list_recent_dost_tasks(*a, **k):  # type: ignore[no-redef]
        return []

JARVIS_DIR = Path(__file__).resolve().parent / "jarvis_memory"
JARVIS_DIR.mkdir(parents=True, exist_ok=True)
PENDING_FILE = JARVIS_DIR / "pending_actions.json"

CACHE_TTL = 60  # seconds — live context is cached this long
_ctx_cache = {"ts": 0.0, "text": ""}


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    confirmed: bool = False
    dry_run: bool = True


# ---------------------------------------------------------------- router ---
def route(text: str) -> Optional[ToolCall]:
    """Match natural language to a Jarvis tool. Returns None for plain chat."""
    t = text.strip()
    tl = t.lower()

    # ----- read-only tools (run unattended) -----
    if re.search(r"\b(fleet|dispatcher|how.?s the fleet|tasks? running|systems? )\b", tl):
        return ToolCall("fleet_status")
    if re.search(r"\b(recent tasks?|what.?s (it|the fleet) (done|working on)|what have (we|i) done)\b", tl):
        return ToolCall("recent_tasks")
    if re.search(r"\b(alerts?|anything wrong|problems|fleet health|health check)\b", tl):
        return ToolCall("alerts")
    if re.search(r"\b(remember|last time|we talked about|what did (i|we) say)\b", tl):
        return ToolCall("recall")

    # ----- action tools (require confirm) -----
    if re.search(r"\b(debate|compare (agents|models))\b", tl):
        return ToolCall("debate", {"prompt": text}, confirmed=False, dry_run=True)
    if tl.startswith(("run ", "start ", "dispatch ", "audit ", "check out ", "execute ", "do ")):
        return ToolCall("dispatch", {"task": text}, confirmed=False, dry_run=True)

    return None


# ---------------------------------------------------------------- tools ----
def fleet_status() -> str:
    """Live fleet context — includes the dispatcher status line."""
    return build_cached_context()


def recent_tasks(limit: int = 8) -> str:
    tasks = list_recent_dost_tasks(limit=limit)
    if not tasks:
        return "No recent dost tasks found."
    lines = ["Recent dost tasks:"]
    for t in tasks:
        lines.append(
            "- {tid} [{status}] {dept}: {task}".format(
                tid=t["task_id"],
                status=t.get("status", "?"),
                dept=t.get("routed_department", "?"),
                task=t.get("task", "")[:70],
            )
        )
    return "\n".join(lines)


def alerts() -> str:
    findings = check_fleet_health()
    if not findings:
        return "Fleet health check: no open alerts."
    lines = ["Open fleet alerts:"]
    for a in findings[:10]:
        lines.append("- {sev}: {msg}".format(sev=a.get("severity", "?").upper(), msg=a.get("message", "")[:90]))
    return "\n".join(lines)


def recall(text: str) -> str:
    recent = conversation_memory.get_recent_context(limit=6)
    if not recent:
        return "I don't have anything stored from earlier conversations yet."
    hits = [i for i in recent if _word_overlap(text, i.get("content", "")) > 0]
    source = hits if hits else recent[-3:]
    lines = ["From what you've told me:"]
    for i in source:
        content = i.get("content", "")[:100]
        role = i.get("role", "you")
        lines.append("- {role}: {content}".format(role=role, content=content))
    return "\n".join(lines)


def _word_overlap(a: str, b: str) -> int:
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    return len(wa & wb)


def dispatch(text: str, confirmed: bool, dry_run: bool) -> str:
    """Route a task to the fleet. Confirmed+dry_run=False writes a real task file."""
    dept = route_department(text)
    if not confirmed and dry_run:
        # Show what would happen without writing.
        return (
            "I'd dispatch this to the {dept} department as \"{task}\". "
            "Say \"yes\" to confirm and I'll send it to the fleet."
        ).format(dept=dept, task=text[:70])
    if not confirmed:
        return "I need an explicit \"yes\" before I dispatch anything to the fleet."
    try:
        from dost import dispatch_prompt_to_fleet
        result = dispatch_prompt_to_fleet(text, dry_run=False)
        MEMORY.add_interaction(text, "jarvis", "Dispatched to fleet: {0}".format(result.get("task_id", "?")))
        return "Dispatched to the fleet as task {task_id} ({dept}). I'll let you know when it's done.".format(
            task_id=result.get("task_id", "?"), dept=dept)
    except Exception as e:  # noqa: BLE001
        return "Dispatch failed: {0}".format(str(e)[:120])


def debate(prompt: str, confirmed: bool, dry_run: bool) -> str:
    if not confirmed:
        return (
            "I'd run a multi-agent debate on \"{prompt}\". Say \"yes\" to confirm."
        ).format(prompt=prompt[:70])
    try:
        from dost import dispatch_debate_to_fleet
        result = dispatch_debate_to_fleet(prompt)
        MEMORY.add_interaction(prompt, "jarvis", "Debate dispatched: {0}".format(result))
        return "Debate dispatched: {0}".format(result)
    except Exception as e:  # noqa: BLE001
        return "Debate failed: {0}".format(str(e)[:120])


# ---------------------------------------------------------------- context --
def build_cached_context() -> str:
    """Live context packet, cached briefly so every reply doesn't re-scan."""
    now = time.time()
    if now - _ctx_cache["ts"] < CACHE_TTL and _ctx_cache["text"]:
        return _ctx_cache["text"]

    parts = [build_context()]
    try:
        parts.append("Fleet: " + fleet_status_dispatcher_line())
    except Exception:  # pragma: no cover - defensive
        parts.append("Fleet: unreachable.")
    try:
        alerts = check_fleet_health()
        if alerts:
            parts.append("Open alerts: " + "; ".join(a.get("message", "")[:60] for a in alerts[:5]))
    except Exception:  # pragma: no cover - defensive
        pass
    summary = conversation_memory.get_context_summary()
    if summary:
        parts.append("Memory: " + summary)

    text = "\n".join(parts)
    _ctx_cache["ts"] = now
    _ctx_cache["text"] = text
    return text


def fleet_status_dispatcher_line() -> str:
    from dost import dispatcher_status_line
    return dispatcher_status_line()


# ---------------------------------------------------------------- execute --
def execute(call: ToolCall, confirmed: bool = False) -> str:
    """Run a routed tool and return prose to inject into the reply."""
    if call.name == "fleet_status":
        return fleet_status()
    if call.name == "recent_tasks":
        return recent_tasks()
    if call.name == "alerts":
        return alerts()
    if call.name == "recall":
        return recall(call.args.get("text", ""))
    if call.name == "dispatch":
        return dispatch(call.args.get("task", ""), confirmed=confirmed, dry_run=call.dry_run)
    if call.name == "debate":
        return debate(call.args.get("prompt", ""), confirmed=confirmed, dry_run=call.dry_run)
    return "I don't have a tool for that yet."


# ---------------------------------------------------------------- pending --
def store_pending(text: str, call: ToolCall) -> None:
    """Remember an unconfirmed action so a follow-up "yes" can resolve it."""
    pending = _load_pending()
    pending.append({"text": text, "call": {"name": call.name, "args": call.args, "dry_run": call.dry_run}, "ts": time.time()})
    pending = pending[-20:]
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)


def resolve_pending(text: str) -> Optional[str]:
    """If the user said yes/no to the last pending action, resolve it."""
    pending = _load_pending()
    if not pending:
        return None
    tl = text.strip().lower()
    if tl in ("yes", "y", "confirm", "do it", "send it", "go"):
        last = pending[-1]
        call = ToolCall(name=last["call"]["name"], args=last["call"]["args"], confirmed=True, dry_run=last["call"]["dry_run"])
        pending.pop()
        _save_pending(pending)
        return execute(call, confirmed=True)
    if tl in ("no", "n", "cancel", "abort", "stop"):
        pending.pop()
        _save_pending(pending)
        return "Cancelled — nothing was dispatched."
    return None


def _load_pending() -> list:
    try:
        with open(PENDING_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_pending(pending: list) -> None:
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)
