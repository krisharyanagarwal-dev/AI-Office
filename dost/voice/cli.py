"""Voice CLI module for dost voice pipeline.

Simple entry point: voice in -> chat -> fleet dispatch -> voice out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dost import dost_respond
from .stt import transcribe
from .tts import synthesize


def dispatch_to_fleet(prompt: str, department: str = "assistant", priority: str = "normal") -> dict:
    """Dispatch prompt to fleet via dost CLI --dispatch."""
    import subprocess
    import json

    # Use dost CLI to dispatch
    cmd = [
        sys.executable,
        "-m", "dost.dost",
        "--department", department,
        "--dispatch", prompt,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"ok": False, "error": result.stderr.strip() or "dispatch failed"}
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

    if parsed.audio:
        # Voice mode: audio -> STT -> dispatch -> TTS
        result = process_voice_input(parsed.audio)
        if result.get("ok"):
            print(json.dumps(result))
        else:
            print(json.dumps(result), file=sys.stderr)
            return 1
    elif parsed.prompt:
        # Text mode: prompt -> dispatch -> response
        result = dispatch_to_fleet(parsed.prompt, parsed.department, parsed.priority)
        if result.get("ok"):
            spoken = f"Task dispatched: {result.get('task_id')} to {result.get('agent_id')}"
            print(json.dumps({**result, "spoken": spoken}))
        else:
            print(json.dumps(result), file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())