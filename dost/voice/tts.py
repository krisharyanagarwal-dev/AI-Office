"""Text-to-speech module for dost voice pipeline.

Wraps openai_components.text_to_speech with a simpler interface for testing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai_components import text_to_speech as _text_to_speech


def synthesize(text: str, output_path: str | Path) -> None:
    """Synthesize text to speech audio file.

    Args:
        text: Text to speak
        output_path: Path to write audio file (mp3 or wav)
    """
    result = _text_to_speech(text, output_path=str(output_path))
    if not result.get("ok"):
        raise RuntimeError(f"TTS failed: {result.get('error')}")


def synthesize_with_metadata(text: str, output_path: str | Path | None = None) -> dict:
    """Synthesize with full metadata.

    Returns:
        Dict with: ok (bool), path (str), provider (str), error (str|None)
    """
    if output_path is None:
        import tempfile
        output_path = str(Path(tempfile.mkstemp(suffix=".mp3")[1]))

    result = _text_to_speech(text, output_path=str(output_path))
    return {
        "ok": result.get("ok", False),
        "path": result.get("path", str(output_path)),
        "provider": result.get("provider", "unknown"),
        "error": result.get("error"),
    }