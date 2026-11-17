#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Voice CLI.

Mic capture (ffmpeg avfoundation) -> Groq Whisper STT -> dost_respond ->
local TTS (say + ffmpeg) -> afplay playback. Ctrl+C to exit.

Paper only. Free tiers only. No Telegram, no tokens needed beyond GROQ_API_KEY.
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai_components import speech_to_text, text_to_speech  # noqa: E402
from dost import dost_respond  # noqa: E402

# avfoundation audio-only input: ":<index>" -> MacBook Air Microphone is index 0.
MIC_DEVICE = ":0"
SAMPLE_RATE = 16000
CHANNELS = 1

# Set by the SIGINT handler to request a clean exit (also interrupts playback).
STOP = threading.Event()


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Dost voice CLI loop")
    parser.add_argument("--seconds", type=int, default=5,
                        help="seconds to record each turn (default: 5)")
    parser.add_argument("--once", action="store_true",
                        help="run a single turn then exit")
    args = parser.parse_args()

    print("=== THE CLAUDE COMPANY — Dost Voice CLI ===")
    print("Mic:     ffmpeg avfoundation :0 (MacBook Air Microphone)")
    print("STT:     Groq whisper-large-v3-turbo")
    print("TTS:     local say + ffmpeg")
    print("Playback: afplay")
    print("Press Ctrl+C to exit.\n")

    def handle_sigint(signum, frame):
        STOP.set()
        print("\n[voice] Ctrl+C — exiting cleanly...")

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        while not STOP.is_set():
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
