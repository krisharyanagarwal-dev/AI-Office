#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost talk + chat at the same time.

Two lanes run side by side:
  * Voice lane (background thread): record -> Groq Whisper -> dost -> speak reply.
  * Chat lane (main thread): type a message -> dost -> print reply (no speech).

dost_respond calls are serialised with a lock so the two lanes never run the
model at the same moment. The voice lane records only after its own reply has
finished playing, so the speaker is not picked up by the mic.

Commands while running:
  /mute     pause the voice lane (typing still works)
  /listen   resume the voice lane
  /quit     exit

Paper only. Free tiers only. Reuses voice_cli.py for mic, STT and playback.
"""
from __future__ import annotations

import argparse
import signal
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice import voice_cli  # noqa: E402  (mic capture, playback, shared STOP event)
from dost import dost_respond  # noqa: E402
from openai_components import speech_to_text, text_to_speech  # noqa: E402

PRINT_LOCK = threading.Lock()   # keeps lines from the two lanes from tangling
DOST_LOCK = threading.Lock()    # one model call at a time
LISTENING = threading.Event()   # set = voice lane is allowed to record
LISTENING.set()


def say_line(text: str) -> None:
    with PRINT_LOCK:
        print(text, flush=True)


def ask_dost(text: str) -> str:
    with DOST_LOCK:
        return dost_respond(text)


def voice_turn(seconds: int) -> None:
    """One voice turn: record, transcribe, answer, speak. Blocking."""
    wav_path = str(Path(tempfile.mkstemp(suffix=".wav")[1]))
    try:
        if not voice_cli.record_audio(seconds, wav_path):
            return
        stt = speech_to_text(wav_path)
        if not stt.get("ok"):
            say_line(f"  [voice] STT failed: {stt.get('error')}")
            return
        heard = (stt.get("text") or "").strip()
        if not heard:
            return
        say_line(f"  [you said] {heard}")
        reply = ask_dost(heard)
        say_line(f"  [dost] {reply}")
        tts = text_to_speech(reply)
        if not tts.get("ok"):
            say_line(f"  [voice] TTS failed: {tts.get('error')}")
            return
        voice_cli.play_audio(tts["path"])
        try:
            Path(tts["path"]).unlink()
        except OSError:
            pass
    finally:
        try:
            Path(wav_path).unlink()
        except OSError:
            pass


def voice_lane(seconds: int) -> None:
    while not voice_cli.STOP.is_set():
        if not LISTENING.wait(0.5):
            continue
        voice_turn(seconds)


def chat_lane() -> None:
    while not voice_cli.STOP.is_set():
        try:
            line = input("you> ").strip()
        except EOFError:
            voice_cli.STOP.set()
            break
        if not line:
            continue
        if line == "/quit":
            voice_cli.STOP.set()
            break
        if line == "/mute":
            LISTENING.clear()
            say_line("[voice] paused. Type /listen to resume.")
            continue
        if line == "/listen":
            LISTENING.set()
            say_line("[voice] listening again.")
            continue
        say_line(f"[dost] {ask_dost(line)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk and chat with dost at the same time")
    parser.add_argument("--seconds", type=int, default=5,
                        help="seconds the mic records per voice turn (default: 5)")
    parser.add_argument("--no-voice", action="store_true",
                        help="chat only, no microphone (useful for testing)")
    args = parser.parse_args()

    say_line("=== THE CLAUDE COMPANY — Dost talk + chat ===")
    say_line("Type to chat. Speak to talk. /mute, /listen, /quit.\n")

    signal.signal(signal.SIGINT, lambda s, f: voice_cli.STOP.set())

    voice_thread = None
    if not args.no_voice:
        voice_thread = threading.Thread(target=voice_lane, args=(args.seconds,), daemon=True)
        voice_thread.start()

    chat_lane()

    voice_cli.STOP.set()
    if voice_thread is not None:
        voice_thread.join(timeout=5)
    say_line("[dost] goodbye.")


if __name__ == "__main__":
    main()
