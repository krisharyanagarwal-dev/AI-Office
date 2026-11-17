#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Voice CLI.

Mic capture (ffmpeg avfoundation) -> Groq Whisper STT -> dost_respond ->
local TTS (say + ffmpeg) -> afplay playback. Ctrl+C to exit.

With --dispatch, spoken prompts go to the fleet orchestrator (direct
CloudModelOrchestrator call, same as debate mode) for an immediate spoken
answer, plus a task file written to HIVE_DIR for the record.

Paper only. Free tiers only. No Telegram, no tokens needed beyond GROQ_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

COMPANY_DIR = Path(__file__).resolve().parent.parent
DOST_DIR = Path(__file__).resolve().parent

OFFICE_OS = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
if str(OFFICE_OS) not in sys.path:
    sys.path.insert(0, str(OFFICE_OS))

from core.subs.cloud_orchestrator import CloudModelOrchestrator  # noqa: E402
from context_builder import build_context  # noqa: E402
from dost import (
    dost_respond,
    _call_with_retry,
    _check_pool_cooldowns,
    _cost_units_for_pool,
)  # noqa: E402
from openai_components import speech_to_text, text_to_speech  # noqa: E402

# avfoundation audio-only input: ":<index>" -> MacBook Air Microphone is index 0.
MIC_DEVICE = ":0"
SAMPLE_RATE = 16000
CHANNELS = 1

# Hive dir for writing voice-dispatch task records.
HIVE_DIR = Path("/Users/aryanagarwal/AI-Office/packages/office-os/tasks")

# Multi-turn: last-turn context stored here so follow-ups can reference it.
LAST_DISPATCH_PATH = DOST_DIR / "last_dispatch.json"

# Set by the SIGINT handler to request a clean exit (also interrupts playback).
STOP = threading.Event()


def load_last_dispatch() -> dict | None:
    """Load the previous voice-dispatch turn (task_id, prompt, answer) if any."""
    try:
        return json.loads(LAST_DISPATCH_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_last_dispatch(task_id: str, prompt: str, answer: str) -> None:
    """Persist the last voice-dispatch turn for multi-turn context."""
    try:
        LAST_DISPATCH_PATH.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "prompt": prompt,
                    "answer": answer,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                indent=2,
            )
        )
    except Exception:
        pass


def record_audio(duration: int, wav_path: str) -> bool:
    """Record `duration` seconds of mic audio to wav_path. Returns True on success."""
    if STOP.is_set():
        return False
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "avfoundation", "-i", MIC_DEVICE,
        "-t", str(duration),
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        wav_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
    except subprocess.TimeoutExpired:
        print("  [voice] mic capture timed out")
        return False
    if proc.returncode != 0:
        print(f"  [voice] mic capture failed: {(proc.stderr or '')[-300:]}")
        return False
    return Path(wav_path).exists() and Path(wav_path).stat().st_size > 0


def play_audio(mp3_path: str) -> None:
    """Play mp3 via afplay, honoring STOP so Ctrl+C interrupts playback."""
    proc = subprocess.Popen(["afplay", mp3_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while proc.poll() is None and not STOP.is_set():
            STOP.wait(0.1)
        if proc.poll() is None:
            # Exit requested while playback was still running — stop it.
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_once(duration: int):
    """One STT -> dost -> TTS -> play turn. Returns transcript or None."""
    wav_path = str(Path(tempfile.mkstemp(suffix=".wav")[1]))
    try:
        if STOP.is_set():
            return None
        print(f"\n[voice] recording {duration}s... speak now")
        if not record_audio(duration, wav_path):
            return None
        print("[voice] transcribing...")
        stt = speech_to_text(wav_path)
        if not stt.get("ok"):
            print(f"  [voice] STT failed: {stt.get('error')}")
            return None
        transcript = (stt.get("text") or "").strip()
        provider = stt.get("provider", "?")
        if not transcript:
            print("[voice] (empty transcription — nothing heard, trying again)")
            return None
        print(f"  [voice] heard ({provider}): {transcript}")
        print("[voice] dost thinking...")
        reply = dost_respond(transcript)
        print(f"\n  dost: {reply}\n")
        print("[voice] speaking reply...")
        tts = text_to_speech(reply)
        if not tts.get("ok"):
            print(f"  [voice] TTS failed: {tts.get('error')}")
            return transcript
        play_audio(tts["path"])
        try:
            Path(tts["path"]).unlink()
        except OSError:
            pass
        return transcript
    finally:
        try:
            Path(wav_path).unlink()
        except OSError:
            pass


def run_dispatch_turn(duration: int):
    """One STT -> fleet dispatch -> TTS -> play turn. Returns transcript or None.

    Routes the spoken prompt directly to the fleet orchestrator (same path as
    debate mode) for an immediate spoken answer. Also writes a task file to
    HIVE_DIR for the record (source='dost', metadata.voice_dispatch=true).
    """
    import uuid

    wav_path = str(Path(tempfile.mkstemp(suffix=".wav")[1]))
    try:
        if STOP.is_set():
            return None
        print(f"\n[voice-dispatch] recording {duration}s... speak now")
        if not record_audio(duration, wav_path):
            return None
        print("[voice-dispatch] transcribing...")
        stt = speech_to_text(wav_path)
        if not stt.get("ok"):
            print(f"  [voice-dispatch] STT failed: {stt.get('error')}")
            return None
        transcript = (stt.get("text") or "").strip()
        provider = stt.get("provider", "?")
        if not transcript:
            print("[voice-dispatch] (empty transcription — nothing heard, trying again)")
            return None
        print(f"  [voice-dispatch] heard ({provider}): {transcript}")
        print("[voice-dispatch] submitting to fleet...")

        # Multi-turn: load previous turn context so follow-ups can reference it.
        last = load_last_dispatch()
        context_prefix = ""
        if last and last.get("answer"):
            context_prefix = (
                f"PREVIOUS TURN (context for follow-up):\n"
                f"User asked: {last.get('prompt','')}\n"
                f"Dost answered: {last.get('answer','')[:400]}\n"
                f"---\n"
            )

        # Build live context (reads :8083/metrics) and submit directly to the
        # fleet orchestrator — same orchestration as debate mode, bypassing
        # the dispatcher's general-assistant override so we get an answer now.
        context = build_context()
        orchestrator = CloudModelOrchestrator()
        full_prompt = (
            f"{context_prefix}{context}\n\n"
            f"Answer the following spoken request from the user directly and "
            f"concisely. Use the live fleet metrics above where relevant. If the "
            f"user is following up on the previous turn, continue that thread.\n\n"
            f"USER SAID: {transcript}"
        )

        task_id = f"jev-{uuid.uuid4().hex[:8]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        answer_text = None
        model_used = None
        pool_used = None
        error = None
        # Cooldown-aware selection + auto-retry on provider failure.
        pool_cooldowns = _check_pool_cooldowns()
        agent_info = {"agent_id": "general-assistant", "tier": "general"}
        answer_text, model_used, pool_used, error = _call_with_retry(
            orchestrator,
            agent_info,
            full_prompt,
            task_id=f"voice-dispatch-{task_id}",
            pool_cooldowns=pool_cooldowns,
            max_retries=2,
        )

        # Persist this turn for multi-turn context (success or failure).
        try:
            save_last_dispatch(task_id, transcript, answer_text or "")
        except Exception:
            pass

        # Write task file for the record.
        task = {
            "id": task_id,
            "title": f"Voice dispatch: {transcript[:60]}",
            "description": transcript,
            "status": "done" if answer_text else "error",
            "agent_id": "general-assistant",
            "priority": "normal",
            "user_id": "dost",
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "tier": "general",
                "source": "dost",
                "voice_dispatch": True,
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

        if answer_text:
            cost = _cost_units_for_pool(pool_used) if pool_used else 0
            print(f"\n  dost (fleet): {answer_text}\n")
            print(f"  [voice-dispatch] cost: {cost} cost_units | pool: {pool_used or '?'}")
            print("[voice-dispatch] speaking reply...")
            tts = text_to_speech(answer_text)
            if not tts.get("ok"):
                print(f"  [voice-dispatch] TTS failed: {tts.get('error')}")
            else:
                play_audio(tts["path"])
                try:
                    Path(tts["path"]).unlink()
                except OSError:
                    pass
        else:
            print(f"  [voice-dispatch] fleet error: {error}")
            print("    Try again — provider may be cooling down.")

        return transcript
    finally:
        try:
            Path(wav_path).unlink()
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Dost voice CLI loop")
    parser.add_argument("--seconds", type=int, default=5,
                        help="seconds to record each turn (default: 5)")
    parser.add_argument("--once", action="store_true",
                        help="run a single turn then exit")
    parser.add_argument("--dispatch", action="store_true",
                        help="route spoken prompts to the fleet orchestrator "
                             "(immediate answer via direct cloud call)")
    args = parser.parse_args()

    print("=== THE CLAUDE COMPANY — Dost Voice CLI ===")
    print("Mic:     ffmpeg avfoundation :0 (MacBook Air Microphone)")
    print("STT:     Groq whisper-large-v3-turbo")
    print("TTS:     local say + ffmpeg")
    print("Playback: afplay")
    if args.dispatch:
        print("Mode:    fleet dispatch (direct cloud call per turn)")
    else:
        print("Mode:    dost conversation (dost_respond)")
    print("Press Ctrl+C to exit.\n")

    def handle_sigint(signum, frame):
        STOP.set()
        print("\n[voice] Ctrl+C — exiting cleanly...")

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        while not STOP.is_set():
            if args.dispatch:
                run_dispatch_turn(args.seconds)
            else:
                run_once(args.seconds)
            if args.once:
                break
            if not STOP.is_set():
                print("[voice] next turn starting...")
    except KeyboardInterrupt:
        STOP.set()
        print("\n[voice] exiting cleanly.")
    finally:
        print("[voice] goodbye.")


if __name__ == "__main__":
    main()
