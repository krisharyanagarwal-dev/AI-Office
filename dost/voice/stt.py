"""Speech-to-text module for dost voice pipeline.

Wraps openai_components.speech_to_text with a simpler interface for testing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai_components import speech_to_text as _speech_to_text


def transcribe(audio_path: str | Path) -> str:
    """Transcribe audio file to text.

    Args:
        audio_path: Path to audio file (wav, mp3, etc.)

    Returns:
        Transcribed text, or empty string on failure.
    """
    result = _speech_to_text(str(audio_path))
    if result.get("ok"):
        return result.get("text", "").strip()
    return ""


def transcribe_with_metadata(audio_path: str | Path) -> dict:
    """Transcribe with full metadata.

    Returns:
        Dict with: ok (bool), text (str), provider (str), error (str|None)
    """
    result = _speech_to_text(str(audio_path))
    return {
        "ok": result.get("ok", False),
        "text": result.get("text", "").strip(),
        "provider": result.get("provider", "unknown"),
        "error": result.get("error"),
    }