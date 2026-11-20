#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Microsoft Teams Bot

Raw HTTP Teams integration (no botbuilder SDK). Handles:

  • Incoming messages → dost response (companion_respond)
  • Text commands: status, dispatch <prompt>, debate <question>, findings

Security: every incoming request must pass validate_teams_signature() (HMAC-SHA256
over the body with the Microsoft app password / signing secret). Fails closed
(False) when no secret is configured.

Send goes to the Bot Framework REST API (v3 conversations/{id}/activities).

Run: import the functions into an HTTP adapter (e.g. Flask/FastAPI route) that
makes the Teams messaging endpoint available.
Env: TEAMS_BOT_TOKEN (or TEAMS_APP_PASSWORD), TEAMS_SIGNING_SECRET in ~/.env
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

COMPANY_DIR = Path(__file__).resolve().parent.parent.parent
DOST_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPANY_DIR))

# Load the inner dost module (dost/dost.py) directly by file path. Importing
# the plain name "dost" is ambiguous here: a top-level dost.py wrapper and a
# dost/ package both exist, and "from dost import ..." would bind to the
# empty package __init__ when this module is imported as dost.teams_bot.
_DOST_INNER = DOST_DIR / "dost.py"
_dost_spec = importlib.util.spec_from_file_location("dost_inner", _DOST_INNER)
_dost = importlib.util.module_from_spec(_dost_spec)
sys.modules["dost_inner"] = _dost
_dost_spec.loader.exec_module(_dost)  # noqa: E402

companion_respond = _dost.companion_respond
dispatch_debate_to_fleet = _dost.dispatch_debate_to_fleet
dispatch_prompt_to_fleet = _dost.dispatch_prompt_to_fleet
dispatcher_status_line = _dost.dispatcher_status_line


def _read_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path.home() / ".env"
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


_ENV = _read_env_file()
TEAMS_BOT_TOKEN = (
    os.environ.get("TEAMS_BOT_TOKEN")
    or _ENV.get("TEAMS_BOT_TOKEN")
    or _ENV.get("TEAMS_APP_PASSWORD", "")
)
TEAMS_SIGNING_SECRET = (
    os.environ.get("TEAMS_SIGNING_SECRET")
    or _ENV.get("TEAMS_SIGNING_SECRET")
    or _ENV.get("TEAMS_APP_PASSWORD", "")
)
# Bot Framework REST base (US region; set TEAMS_BASE_URL to override).
TEAMS_BASE_URL = os.environ.get("TEAMS_BASE_URL") or _ENV.get(
    "TEAMS_BASE_URL", "https://smba.trafficmanager.net/us/v3"
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Teams HTTP helpers
# ---------------------------------------------------------------------------

def _teams(method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    """Call the Bot Framework REST API. Returns parsed JSON or {} on failure."""
    if not TEAMS_BOT_TOKEN:
        return {}
    url = f"{TEAMS_BASE_URL}{path}"
    try:
        cmd = [
            "curl", "-s", "-X", method.upper(), url,
            "-H", f"Authorization: Bearer {TEAMS_BOT_TOKEN}",
            "-H", "Content-Type: application/json",
        ]
        if payload is not None:
            cmd += ["-d", json.dumps(payload)]
        cmd += ["--max-time", str(timeout)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def validate_teams_signature(body: str | bytes, signature: str) -> bool:
    """Verify a Teams request signature (HMAC-SHA256 over the body).

    Compares the provided signature against HMAC-SHA256(key=signing secret,
    msg=body). Returns False when no signing secret is configured (fail closed)
    or when the signatures do not match.
    """
    if not TEAMS_SIGNING_SECRET or not signature:
        return False
    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body
    expected = hmac.new(
        TEAMS_SIGNING_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _strip_mention(text: str) -> str:
    """Strip Teams <at> mentions and a leading '@dost' / 'dost' prefix."""
    t = re.sub(r"<at[^>]*>.*?</at>", "", text or "", flags=re.I | re.S)
    t = re.sub(r"^@?dost\b\s*", "", t, flags=re.I).strip()
    return t


def _status_text() -> str:
    return dispatcher_status_line()


def _dispatch_text(prompt: str) -> str:
    result = dispatch_prompt_to_fleet(prompt)
    if not result.get("ok"):
        return f"❌ Dispatch failed: {result.get('error', 'unknown error')}"
    return (
        f"✅ Dispatched to fleet (task {result.get('task_id')}). "
        f"Agent: {result.get('agent_id')} — the dispatcher will run it on the next cycle."
    )


def _debate_text(question: str) -> str:
    result = dispatch_debate_to_fleet(question)
    if not result.get("ok"):
        return f"❌ Debate failed: {result.get('error', 'unknown error')}"
    synthesis = (result.get("synthesis") or "").strip()
    answers = result.get("answers") or []
    n = len(answers)
    ok_n = sum(1 for a in answers if not a.get("error"))
    lines = [f"🗣️ Debate: {question}", f"• {ok_n} of {n} agents answered."]
    if synthesis:
        lines.append(f"• {synthesis}")
    return "\n".join(lines)


def _findings_text(limit: int = 6) -> str:
    """Summarise the most recent collaborative findings across workspaces."""
    root = Path(os.path.expanduser("~/.openclaw/workspaces"))
    items: list[tuple[float, str, str]] = []  # (mtime, workspace_id, finding_id)
    if root.is_dir():
        for ws in root.iterdir():
            if not ws.is_dir():
                continue
            fdir = ws / "findings"
            if not fdir.is_dir():
                continue
            for finding in fdir.iterdir():
                if not finding.is_dir():
                    continue
                try:
                    mtime = finding.stat().st_mtime
                except OSError:
                    continue
                items.append((mtime, ws.name, finding.name))
    items.sort(reverse=True)
    if not items:
        return "📋 No collaborative findings yet."
    lines = [f"📋 Recent findings (top {min(limit, len(items))}):"]
    for _, ws_id, finding_id in items[:limit]:
        meta = _read_json(root / ws_id / "findings" / finding_id / "finding.json")
        title = meta.get("title") or meta.get("summary") or finding_id
        lines.append(f"• [{ws_id}] {title}")
    return "\n".join(lines)


def _route_teams_text(message_text: str) -> str:
    """Route a Teams message text to the right dost response."""
    text = (message_text or "").strip()
    if not text:
        return "I didn't catch that — say something, or try: dost status, dost dispatch <prompt>, dost debate <question>, dost findings."

    core = _strip_mention(text)
    lowered = core.lower()

    if lowered in ("help", "dost help"):
        return (
            "*Dost — THE CLAUDE COMPANY* (Teams)\n"
            "• dost status — fleet + P&L + provider health\n"
            "• dost dispatch <prompt> — send a prompt to the fleet\n"
            "• dost debate <question> — fan a question to pro agents + synthesis\n"
            "• dost findings — recent collaborative findings\n"
            "Or just send me a message and I'll reply."
        )
    if lowered == "status":
        return _status_text()
    if lowered.startswith("dispatch") or lowered.startswith("/dost dispatch"):
        rest = _strip_mention(text)
        rest = re.sub(r"^@?dost\b\s*", "", rest, flags=re.I).strip()
        rest = re.sub(r"^dispatch\b\s*", "", rest, flags=re.I).strip()
        if not rest:
            return "Usage: dost dispatch <prompt>"
        return _dispatch_text(rest)
    if lowered.startswith("debate"):
        rest = _strip_mention(text)
        rest = re.sub(r"^@?dost\b\s*", "", rest, flags=re.I).strip()
        rest = re.sub(r"^debate\b\s*", "", rest, flags=re.I).strip()
        if not rest:
            return "Usage: dost debate <question>"
        return _debate_text(rest)
    if lowered == "findings":
        return _findings_text()

    # Free text → the dost brain
    try:
        return companion_respond(text)
    except Exception:
        return ("I'm having trouble thinking straight right now. "
                "Try: dost status, dost dispatch <prompt>, "
                "dost debate <question>, or dost findings.")


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------

def handle_teams_message(message_text: str, user_id: str, conversation_id: str) -> dict:
    """Handle an incoming Teams message.

    Routes commands (status/dispatch/debate/findings) and falls back to
    companion_respond() for free text, then sends the reply back to the
    conversation. Returns a dict describing what was done.
    """
    text = (message_text or "").strip()
    if not text:
        return {"ok": False, "handled": False, "reason": "empty message"}

    reply = _route_teams_text(text)
    sent = False
    if conversation_id:
        sent = send_teams_message(conversation_id, reply)

    return {
        "ok": sent,
        "handled": True,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "reply": reply,
    }


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_teams_message(conversation_id: str, text: str) -> bool:
    """Send a message to a Teams conversation. Returns True on success."""
    if not conversation_id or not text:
        return False
    activity: dict[str, Any] = {
        "type": "message",
        "text": text,
    }
    result = _teams("POST", f"/conversations/{conversation_id}/activities", activity)
    # Teams returns the created activity JSON (with an "id") on success.
    return bool(result)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def handle_teams_event(event: dict) -> dict:
    """Handle a generic Teams webhook event (message, conversationUpdate, etc.).

    Message events are routed through handle_teams_message. Other event types
    are acknowledged and described.
    """
    event_type = event.get("type")
    if event_type == "message":
        message_text = event.get("text", "")
        user_id = event.get("from", {}).get("id", "") if isinstance(event.get("from"), dict) else event.get("from", "")
        conversation_id = (
            event.get("conversation", {}).get("id", "")
            if isinstance(event.get("conversation"), dict)
            else event.get("conversation_id", "")
        )
        return handle_teams_message(message_text, user_id, conversation_id)

    return {
        "ok": True,
        "handled": False,
        "type": event_type,
        "reason": "event type not handled by the bot",
    }


if __name__ == "__main__":
    print("teams_bot.py: importable module (no long-running loop).")
