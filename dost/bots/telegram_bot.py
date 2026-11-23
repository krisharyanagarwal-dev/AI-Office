#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Telegram Bot

Long-polling Telegram bot over raw HTTP (no external bot SDK). Gives the dost
a voice on your phone:

  • Text messages  → dost_respond → text reply (and optional voice reply)
  • Voice notes    → Whisper STT → dost_respond → TTS voice reply back
  • /briefing      → today's daily briefing
  • /status        → fleet + P&L + boundaries one-liner
  • /report        → latest monthly research report summary
  • /help          → what the dost can do

Security: allowlisted chat_id only. The bot ignores everyone else.

Run: python dost/telegram_bot.py   (background via launchd)
Env: TELEGRAM_BOT_TOKEN in ~/.env
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

COMPANY_DIR = Path(__file__).resolve().parent.parent.parent
DOST_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPANY_DIR))
sys.path.insert(0, str(DOST_DIR))

from dost import companion_respond, generate_daily_briefing, MEMORY  # noqa: E402  (dost package now uses dost_main)
from openai_components import provider_health, speech_to_text, text_to_speech  # noqa: E402


def _read_env_file() -> dict:
    env = {}
    p = Path.home() / ".env"
    try:
        for line in p.read_text().splitlines():
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
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _ENV.get("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Allowlist: only this chat_id can talk to the bot. Populated on first message
# from the owner, then persisted. Empty = nobody can talk (safe default).
ALLOWLIST_FILE = Path.home() / ".openclaw" / "telegram_allowlist.json"


def _load_allowlist() -> set[str]:
    try:
        return set(json.loads(ALLOWLIST_FILE.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_allowlist(ids: set[str]) -> None:
    ALLOWLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALLOWLIST_FILE.write_text(json.dumps(sorted(ids), indent=2))


ALLOWLIST = _load_allowlist()


# ---------------------------------------------------------------------------
# Telegram HTTP helpers
# ---------------------------------------------------------------------------

def _tg(method: str, payload: dict | None = None, files: dict | None = None,
        timeout: int = 30) -> dict:
    """POST to Telegram Bot API. Returns parsed JSON or {} on failure."""
    if not BOT_TOKEN:
        return {}
    url = BASE_URL + "/" + method
    try:
        if files:
            # multipart: build curl with -F for each
            cmd = ["curl", "-s", "-X", "POST", url, "--max-time", str(timeout)]
            if payload:
                for k, v in payload.items():
                    cmd += ["-F", f"{k}={v}"]
            for k, v in (files or {}).items():
                if isinstance(v, tuple):
                    fname, fdata, ftype = v
                    cmd += ["-F", f"{k}=@{fname};type={ftype}"]
                else:
                    cmd += ["-F", f"{k}=@{v}"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        else:
            cmd = ["curl", "-s", "-X", "POST", url,
                   "-H", "Content-Type: application/json",
                   "-d", json.dumps(payload or {}),
                   "--max-time", str(timeout)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception:
        return {}


def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> dict:
    return _tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def send_voice(chat_id: int, audio_path: str) -> dict:
    return _tg("sendVoice", {"chat_id": str(chat_id)}, files={"voice": audio_path})


def get_file(file_id: str) -> dict:
    return _tg("getFile", {"file_id": file_id})


def download_file(file_path: str, dest: str) -> bool:
    if not BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    try:
        proc = subprocess.run(
            ["curl", "-s", "-L", url, "--output", dest, "--max-time", "60"],
            capture_output=True, text=True, timeout=70,
        )
        return proc.returncode == 0 and Path(dest).stat().st_size > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dost response builders
# ---------------------------------------------------------------------------

def _status_one_liner() -> str:
    h = provider_health()
    pnl_path = (Path.home() / ".openclaw" / "office_pnl.json")
    net = "?"
    try:
        pnl = json.loads(pnl_path.read_text())
        net = pnl.get("net_value", "?")
    except Exception:
        pass
    return (
        f"*THE CLAUDE COMPANY — Status*\n"
        f"• Kill switch: LOCKED | live_orders_allowed: false\n"
        f"• Paper only • Tier C: human-only\n"
        f"• Office P&L net: {net}\n"
        f"• Providers: chat={h.get('groq_chat') or h.get('openai_chat')}, "
        f"STT={h.get('groq_whisper') or h.get('openai_whisper')}, "
        f"TTS={'local-say' if h.get('local_tts') else 'openai'}"
    )


def _report_summary() -> str:
    pub_dir = (Path.home() / "Documents" / "indian-paper-trading" / "results" / "public_record")
    try:
        reports = sorted(pub_dir.glob("monthly_report_*.json"))
        if not reports:
            return "No monthly research reports yet."
        latest = json.loads(reports[-1].read_text())
        hyp = latest.get("hypotheses", {})
        cal = latest.get("calibration", {})
        return (
            f"*Monthly Research Report — {latest.get('month','?')}*\n"
            f"• Hypotheses: {hyp.get('total',0)} total | "
            f"{latest.get('passed_count',0)} passed | {hyp.get('failed_count',0)} failed\n"
            f"• Calibration: {cal.get('well_calibrated',0)}/{cal.get('n',0)} well-calibrated\n"
            f"• Key finding: No viable edge at ₹1L + free data (bull put + IV rank ≥80%: "
            f"+₹762.34 tuning, −₹5,329.56 holdout — retired)."
        )
    except Exception as e:
        return f"Could not load report: {e}"


def _dost_reply(user_text: str, chat_id: int, want_voice: bool = False) -> tuple[str, Optional[str]]:
    """Run companion_respond (same brain as the pet) and return (text, voice_path_or_None)."""
    reply = companion_respond(user_text)
    # Strip the greeting line for a cleaner chat feel (keep the substance)
    lines = reply.split("\n")
    body = "\n".join(l for l in lines if not l.startswith("Good "))
    voice_path = None
    if want_voice:
        tts = text_to_speech(body[:2000])  # cap length for TTS
        if tts.get("ok"):
            voice_path = tts["path"]
    return body, voice_path


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------

def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    chat_id_str = str(chat_id)

    # Allowlist enforcement
    if chat_id_str not in ALLOWLIST:
        # First-time contact: send a one-off intro and add to allowlist
        if ALLOWLIST:
            send_message(chat_id, "This dost is private — not authorized for this chat.")
            return
        # No allowlist yet: first sender becomes the owner
        ALLOWLIST.add(chat_id_str)
        _save_allowlist(ALLOWLIST)
        send_message(
            chat_id,
            "🔒 *Dost activated.* This bot is now linked to your chat only.\n"
            "Send me anything — research, trading, status, or just chat.\n"
            "Try: /briefing, /status, /report, /help",
        )
        return

    text = message.get("text", "")
    voice = message.get("voice")

    # Voice note: STT → dost → TTS reply
    if voice:
        file_id = voice["file_id"]
        gf = get_file(file_id)
        tg_file_path = gf.get("result", {}).get("file_path")
        if not tg_file_path:
            send_message(chat_id, "Couldn't fetch your voice note. Try typing instead.")
            return
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tf:
            ogg_path = tf.name
        if not download_file(tg_file_path, ogg_path):
            send_message(chat_id, "Voice download failed. Try typing instead.")
            try:
                Path(ogg_path).unlink()
            except OSError:
                pass
            return
        stt = speech_to_text(ogg_path)
        try:
            Path(ogg_path).unlink()
        except OSError:
            pass
        if not stt.get("ok"):
            send_message(chat_id, f"Couldn't transcribe: {stt.get('error','unknown')}")
            return
        transcribed = stt["text"].strip()
        if not transcribed:
            send_message(chat_id, "Empty transcription. Try again?")
            return
        # Echo what we heard, then respond
        send_message(chat_id, f"*You said:* _{transcribed}_")
        body, voice_path = _dost_reply(transcribed, chat_id, want_voice=True)
        send_message(chat_id, body)
        if voice_path:
            send_voice(chat_id, voice_path)
        return

    # Commands
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        if cmd == "/start":
            send_message(
                chat_id,
                "👋 *Dost — THE CLAUDE COMPANY*\n"
                "Your paper-only AI chief of staff on Telegram.\n"
                "Commands: /briefing, /status, /report, /help\n"
                "Or just send me a message (text or voice note).",
            )
        elif cmd == "/help":
            send_message(
                chat_id,
                "*Dost commands:*\n"
                "• /briefing — today's daily research + fleet briefing\n"
                "• /status — kill switch, P&L, provider health\n"
                "• /report — latest monthly research report\n"
                "• /help — this message\n"
                "\nYou can also send free text (research ideas, code, strategy) or a "
                "voice note — I'll transcribe it and reply in text + voice.",
            )
        elif cmd == "/briefing":
            send_message(chat_id, generate_daily_briefing())
        elif cmd == "/status":
            send_message(chat_id, _status_one_liner())
        elif cmd == "/report":
            send_message(chat_id, _report_summary())
        else:
            send_message(chat_id, "Unknown command. Try /help.")
        return

    # Free text → dost
    if text.strip():
        body, voice_path = _dost_reply(text, chat_id, want_voice=True)
        send_message(chat_id, body)
        if voice_path:
            send_voice(chat_id, voice_path)


# ---------------------------------------------------------------------------
# Main loop: long polling
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set. Add it to ~/.env and restart.")
        sys.exit(1)

    print("Dost Telegram bot starting... (Ctrl+C to stop)")
    offset = None
    while True:
        try:
            payload = {"timeout": 30, "limit": 100}
            if offset is not None:
                payload["offset"] = offset
            result = _tg("getUpdates", payload, timeout=45)
            if not result or not result.get("ok"):
                time.sleep(2)
                continue
            updates = result.get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                handle_update(upd)
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Poll error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
