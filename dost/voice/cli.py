"""Voice CLI module for dost voice pipeline.

Simple entry point: voice in -> dost_respond (shared memory) -> voice out.

Routes input through the same memory-aware chat path as the CLI, web, and
Telegram interfaces so voice conversations persist across sessions.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dost import dost_respond
from dost.dost_main import dispatch_prompt_to_fleet, sanitize_response
from .stt import transcribe
from .tts import synthesize


def dispatch_to_fleet(prompt: str, department: str = "assistant", priority: str = "normal") -> dict:
    """Dispatch prompt to fleet by writing a task file directly.

    Calls dispatch_prompt_to_fleet in-process instead of shelling out to the
    (removed) dost.dost module. Returns {"ok", "task_id", "agent_id", ...}.
    Read-only data write — no live orders, no trading execution.
    """
    try:
        return dispatch_prompt_to_fleet(
            prompt,
            agent_id=department,
            priority=priority,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}


def process_voice_input(audio_path: str | Path) -> dict:
    """Process voice input: STT -> chat/dispatch -> TTS.

    Returns:
        Dict with: ok, task_id, agent_id, spoken_response, audio_path
    """
    # 1. Transcribe
    text = transcribe(audio_path)
    if not text:
        return {"ok": False, "error": "STT returned empty text"}

    # 2. Dispatch to fleet
    dispatch_result = dispatch_to_fleet(text, department="assistant")
    if not dispatch_result.get("ok"):
        return {"ok": False, "error": dispatch_result.get("error", "Dispatch failed")}

    task_id = dispatch_result.get("task_id", "unknown")
    agent_id = dispatch_result.get("agent_id", "unknown")

    # 3. Generate spoken response
    spoken = f"Task dispatched: {task_id} to {agent_id}"

    # 4. Synthesize (in real usage, this writes to a file)
    # For CLI, we just return the response
    return {
        "ok": True,
        "task_id": task_id,
        "agent_id": agent_id,
        "spoken": spoken,
        "text": text,
    }


def main(args: list[str] | None = None) -> int:
    """Main entry point for voice CLI.

    Usage: python -m dost.voice.cli "prompt text"
           python -m dost.voice.cli --audio path/to/audio.wav

    Routes input through dost_respond (the shared, memory-aware chat path)
    so voice conversations persist across CLI/web/Telegram sessions, then
    speaks the reply via TTS.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Dost voice CLI")
    parser.add_argument("prompt", nargs="?", help="Text prompt (bypasses STT)")
    parser.add_argument("--audio", help="Audio file path for STT")
    parser.add_argument("--department", default="assistant", help="Fleet department")
    parser.add_argument("--priority", default="normal", help="Task priority")
    parser.add_argument("--version", action="store_true", help="Show version")

    parsed = parser.parse_args(args)

    if parsed.version:
        print("dost-voice 1.0.0")
        return 0

    # Resolve input text: from prompt or via STT from audio file.
    text = parsed.prompt
    if parsed.audio:
        text = transcribe(parsed.audio)
        if not text:
            print(json.dumps({"ok": False, "error": "STT returned empty text"}), file=sys.stderr)
            return 1

    if not text:
        parser.print_help()
        return 1

    # Route through the shared, memory-aware chat path so voice
    # conversations persist across CLI/web/Telegram sessions.
    response = dost_respond(
        text,
        department=parsed.department,
        conversation_id="voice-owner",
        interface="voice",
    )

    # Sanitize before printing/speaking so internal routing details and
    # unsafe trading claims never leak into the spoken reply.
    response = sanitize_response(response)
    print(response)

    # Speak the reply (best-effort; never fail the CLI on TTS/audio issues).
    try:
        out = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            synthesize(response, out)
            subprocess.run(["afplay", str(out)], capture_output=True, timeout=30)
        finally:
            try:
                out.unlink()
            except OSError:
                pass
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())