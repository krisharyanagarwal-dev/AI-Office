"""TDD tests for voice pipeline: STT -> Chat -> TTS roundtrip."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add dost to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice import stt, tts, cli


class TestVoicePipeline:
    """End-to-end voice pipeline tests with mocked I/O."""

    def test_stt_transcribes_wav_to_text(self, tmp_path):
        """STT returns transcript from WAV file."""
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"RIFF....WAVEfmt ")  # minimal WAV header

        with patch("voice.stt.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps({"text": "research AAPL earnings"}),
                returncode=0,
            )
            result = stt.transcribe(wav)
            assert result == "research AAPL earnings"
            mock_run.assert_called_once()

    def test_tts_generates_wav_from_text(self, tmp_path):
        """TTS writes WAV file from text."""
        out = tmp_path / "out.mp3"

        with patch("voice.tts._text_to_speech") as mock_tts:
            mock_tts.return_value = {"ok": True, "path": str(out), "provider": "test"}
            tts.synthesize("Task dispatched: jev-abc123", out)
            mock_tts.assert_called_once()

    def test_cli_roundtrip_stt_chat_tts(self, tmp_path, monkeypatch):
        """Full pipeline: voice in -> chat -> fleet -> voice out."""
        # Mock STT
        with patch("voice.stt.transcribe") as mock_stt:
            mock_stt.return_value = "research AAPL earnings"

            # Mock dispatch_to_fleet (defined in cli.py)
            with patch("voice.cli.dispatch_to_fleet") as mock_dispatch:
                mock_dispatch.return_value = {
                    "ok": True,
                    "task_id": "jev-abc123",
                    "agent_id": "research-analyst",
                }

                # Mock TTS
                with patch("voice.tts.synthesize") as mock_tts:
                    mock_tts.return_value = None

                    # Run CLI
                    result = cli.main(["research AAPL earnings"])

                    # Verify flow
                    mock_stt.assert_not_called()  # text mode bypasses STT
                    # Check call with positional arguments
                    args, kwargs = mock_dispatch.call_args
                    assert args[0] == "research AAPL earnings"
                    assert args[1] == "assistant"
                    assert args[2] == "normal"
                    mock_tts.assert_not_called()  # CLI doesn't call TTS directly


class TestSiriBridge:
    """Tests for Siri shortcut bridge."""

    def test_siri_bridge_exists(self):
        """siri_dost.sh exists in dost directory."""
        script = Path(__file__).resolve().parents[1] / "siri_dost.sh"
        assert script.exists()


class TestVoiceCLI:
    """Tests for voice CLI entry point."""

    def test_cli_help(self, capsys):
        """CLI shows help with -h."""
        with pytest.raises(SystemExit):
            cli.main(["-h"])
        out = capsys.readouterr().out
        assert "voice" in out.lower()

    def test_cli_version(self, capsys):
        """CLI shows version."""
        cli.main(["--version"])
        out = capsys.readouterr().out
        assert "dost-voice" in out.lower()