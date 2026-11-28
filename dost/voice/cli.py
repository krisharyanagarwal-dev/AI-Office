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
from dost.dost_main import (
    dispatch_prompt_to_fleet,
    sanitize_response,
    _wait_for_task,
)
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


def speak(text: str) -> None:
    """Synthesize and play text (best-effort; never fail the CLI)."""
    try:
        out = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            synthesize(text, out)
            subprocess.run(["afplay", str(out)], capture_output=True, timeout=30)
        finally:
            try:
                out.unlink()
            except OSError:
                pass
    except Exception:
        pass


def run_dispatch(
    prompt: str,
    department: str = "assistant",
    priority: str = "normal",
    conversation_id: str = "voice-owner",
) -> int:
    """Dispatch a prompt to the fleet, poll for its result, and speak it.

    Prints {"ok", "task_id", "agent_id"} to stdout so callers (e.g. Siri
    Shortcuts) can surface the task id, then speaks the fleet result via TTS
    once the task completes. The turn is recorded to jarvis_memory so voice
    context survives process restarts.
    """
    result = dispatch_prompt_to_fleet(prompt, agent_id=department, priority=priority)
    if not result.get("ok"):
        spoken = sanitize_response(
            f"Fleet dispatch failed: {result.get('error', 'unknown error')}"
        )
        print(json.dumps({"ok": False, "error": spoken}))
        speak(spoken)
        return 1

    task_id = result.get("task_id", "unknown")
    agent_id = result.get("agent_id", "unknown")
    print(json.dumps({"ok": True, "task_id": task_id, "agent_id": agent_id}))

    # Poll until the fleet task completes (or times out).
    task = _wait_for_task(task_id)
    if task is None:
        output = f"Fleet task {task_id} still pending."
    elif task.get("status") == "error":
        output = f"Fleet task errored: {task.get('error', 'unknown error')}"
    else:
        task_result = task.get("result") or {}
        if isinstance(task_result, dict):
            output = task_result.get("text") or task_result.get("preview") or ""
        elif isinstance(task_result, str):
            output = task_result
        else:
            output = ""
    output = output or f"(fleet task {task_id} completed with no result text)"

    spoken = sanitize_response(output)

    # Persist the turn so voice context survives across restarts.
    try:
        from jarvis_memory.session import append_turn

        append_turn(conversation_id, "voice", prompt, spoken)
    except Exception:  # noqa: BLE001
        pass

    speak(spoken)
    return 0


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
    parser.add_argument(
        "--department", default="assistant", help="Fleet department"
    )
    parser.add_argument("--priority", default="normal", help="Task priority")
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Dispatch to fleet, poll for result, and speak it",
    )
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

    if parsed.dispatch:
        return run_dispatch(
            text,
            department=parsed.department,
            priority=parsed.priority,
        )

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
    speak(response)

    return 0


if __name__ == "__main__":
    sys.exit(main())