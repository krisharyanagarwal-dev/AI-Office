#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Slack Bot

Raw HTTP Slack integration (no slack-sdk). Mounts these slash commands:

  • /dost status        → fleet + P&L + provider health one-liner
  • /dost dispatch <prompt> → submit a prompt to the fleet
  • /dost debate <question> → fan a question to pro agents + synthesis
  • /dost findings      → recent collaborative findings summary

Plus a generic event handler for app_mention / message events.

Security: every incoming request must pass validate_slack_signature()
(X-Slack-Signature, HMAC-SHA256 over v0:{timestamp}:{body}); requests older
than 5 minutes are rejected as replays. When no signing secret is configured
validation fails closed (returns False).

Run: import the functions into an HTTP adapter (e.g. Flask/FastAPI route).
Env: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET in ~/.env
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

COMPANY_DIR = Path(__file__).resolve().parent.parent.parent
DOST_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPANY_DIR))

# Load the inner dost module (dost/dost.py) directly by file path. Importing
# the plain name "dost" is ambiguous here: a top-level dost.py wrapper and a
# dost/ package both exist, and "from dost import ..." would bind to the
# empty package __init__ when this module is imported as dost.slack_bot.
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
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN") or _ENV.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = (
    os.environ.get("SLACK_SIGNING_SECRET") or _ENV.get("SLACK_SIGNING_SECRET", "")
)
SLACK_API = "https://slack.com/api"

# Replay window: Slack signatures are only valid within 5 minutes of the timestamp.
SLACK_MAX_AGE_SECONDS = 60 * 5


# ---------------------------------------------------------------------------
# Slack HTTP helpers
# ---------------------------------------------------------------------------

def _slack(method: str, payload: dict | None = None, timeout: int = 30) -> dict:
    """POST to the Slack Web API. Returns parsed JSON or {} on failure."""
    if not SLACK_BOT_TOKEN:
        return {}
    url = f"{SLACK_API}/{method}"
    try:
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {SLACK_BOT_TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload or {}),
            "--max-time", str(timeout),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception:
        return {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

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
        meta = _read_json(Path(root) / ws_id / "findings" / finding_id / "finding.json")
        title = meta.get("title") or meta.get("summary") or finding_id
        lines.append(f"• [{ws_id}] {title}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def validate_slack_signature(body: str | bytes, timestamp: str | int, signature: str) -> bool:
    """Verify an incoming Slack request signature (X-Slack-Signature).

    Slack signs the string v0:{timestamp}:{body} with HMAC-SHA256(key=signing
    secret). Returns False when no signing secret is configured (fail closed),
    when the timestamp is outside the replay window, or when the signatures
    do not match.
    """
    if not SLACK_SIGNING_SECRET or not signature:
        return False
    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > SLACK_MAX_AGE_SECONDS:
        return False
    sig_baseline = b"v0:" + str(ts).encode("ascii") + b":" + body_bytes
    expected = (
        "v0="
        + hmac.new(
            SLACK_SIGNING_SECRET.encode("utf-8"), sig_baseline, hashlib.sha256
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def handle_slack_command(command: str, text: str, user_id: str, channel_id: str) -> dict:
    """Handle a Slack slash command.

    Commands:
      /dost status
      /dost dispatch <prompt>
      /dost debate <question>
      /dost findings

    Returns a response dict (ok, response_type, text) suitable for replying to
    Slack. response_type "ephemeral" means only the invoking user sees it.
    """
    command = (command or "").strip().lower()
    text = (text or "").strip()

    if command != "/dost":
        return {
            "ok": False,
            "response_type": "ephemeral",
            "text": (
                f"Unknown command `{command}`. "
                "Try: /dost status, /dost dispatch <prompt>, "
                "/dost debate <question>, /dost findings."
            ),
        }

    parts = text.split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("help", ""):
        reply = (
            "*Dost — THE CLAUDE COMPANY* (Slack)\n"
            "• /dost status — fleet + P&L + provider health\n"
            "• /dost dispatch <prompt> — send a prompt to the fleet\n"
            "• /dost debate <question> — fan a question to pro agents + synthesis\n"
            "• /dost findings — recent collaborative findings\n"
        )
    elif sub == "status":
        reply = _status_text()
    elif sub == "dispatch":
        if not rest:
            reply = "Usage: /dost dispatch <prompt>"
        else:
            reply = _dispatch_text(rest)
    elif sub == "debate":
        if not rest:
            reply = "Usage: /dost debate <question>"
        else:
            reply = _debate_text(rest)
    elif sub == "findings":
        reply = _findings_text()
    else:
        reply = f"Unknown subcommand `{sub}`. Type /dost help for usage."

    return {"ok": True, "response_type": "ephemeral", "text": reply}


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_slack_message(channel_id: str, text: str, blocks: list[dict] | None = None) -> bool:
    """Send a message to a Slack channel. Returns True on success."""
    if not channel_id or not text:
        return False
    payload: dict[str, Any] = {"channel": channel_id, "text": text}
    if blocks:
        payload["blocks"] = blocks
    result = _slack("chat.postMessage", payload)
    return bool(result.get("ok"))


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def handle_slack_event(event: dict) -> dict:
    """Handle a Slack Events API event (app_mention, message, etc.).

    Free text (or text after a mention) is answered with companion_respond().
    Returns a dict describing what was done.
    """
    event_type = event.get("type")
    message_text = event.get("text") or ""

    if event_type in ("app_mention", "message") and message_text.strip():
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        try:
            reply = companion_respond(message_text)
        except Exception:
            reply = ("I'm having trouble thinking straight right now. "
                     "Try /dost status, /dost dispatch <prompt>, "
                     "/dost debate <question>, or /dost findings.")
        if channel_id:
            send_slack_message(channel_id, reply)
        return {
            "ok": True,
            "handled": True,
            "type": event_type,
            "user_id": user_id,
            "channel_id": channel_id,
        }

    return {"ok": True, "handled": False, "type": event_type}


if __name__ == "__main__":
    print("slack_bot.py: importable module (no long-running loop).")
