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
        """Full pipeline: text -> dost_respond (shared memory) -> TTS speak."""
        # Mock dost_respond (the shared memory-aware chat path)
        with patch("voice.cli.dost_respond") as mock_respond:
            mock_respond.return_value = "Task dispatched: jev-abc123 to research-analyst"

            # Mock TTS (cli holds its own reference to synthesize)
            with patch("voice.cli.synthesize") as mock_tts:
                mock_tts.return_value = None

                # Mock subprocess.run (afplay) so no audio plays in tests
                with patch("voice.cli.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)

                    # Run CLI
                    result = cli.main(["research AAPL earnings"])

                    # Verify flow: dost_respond is called (shared memory path)
                    mock_respond.assert_called_once()
                    args, kwargs = mock_respond.call_args
                    assert args[0] == "research AAPL earnings"
                    assert kwargs.get("conversation_id") == "voice-owner"
                    assert kwargs.get("interface") == "voice"
                    # TTS speaks the response
                    mock_tts.assert_called_once()

    def test_cli_audio_mode_uses_stt_and_dost_respond(self, tmp_path, monkeypatch):
        """Audio mode: STT transcribes, then dost_respond, then TTS speaks."""
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"RIFF....WAVEfmt ")

        with patch("voice.cli.transcribe") as mock_stt:
            mock_stt.return_value = "research AAPL earnings"

            with patch("voice.cli.dost_respond") as mock_respond:
                mock_respond.return_value = "I'll research that for you."

                with patch("voice.cli.synthesize") as mock_tts:
                    mock_tts.return_value = None

                    with patch("voice.cli.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)

                        result = cli.main(["--audio", str(wav)])

                        mock_stt.assert_called_once_with(str(wav))
                        mock_respond.assert_called_once()
                        args, kwargs = mock_respond.call_args
                        assert args[0] == "research AAPL earnings"
                        mock_tts.assert_called_once()


class TestDispatchToFleet:
    """Tests for dispatch_to_fleet: direct in-process call, no subprocess shell-out."""

    def test_dispatch_to_fleet_calls_dost_main_directly(self, monkeypatch):
        """dispatch_to_fleet calls dispatch_prompt_to_fleet in-process, never shells out."""
        calls = []

        def fake_dispatch(prompt, agent_id=None, priority="normal", **kwargs):
            calls.append((prompt, agent_id, priority))
            return {
                "ok": True,
                "task_id": "jev-abcd1234",
                "agent_id": agent_id or "strategy-advisor",
            }

        monkeypatch.setattr(cli, "dispatch_prompt_to_fleet", fake_dispatch)
        with patch("voice.cli.subprocess.run") as mock_run:
            result = cli.dispatch_to_fleet(
                "research AAPL earnings", department="research", priority="high"
            )

        assert result == {
            "ok": True,
            "task_id": "jev-abcd1234",
            "agent_id": "research",
        }
        assert calls == [("research AAPL earnings", "research", "high")]
        mock_run.assert_not_called()

    def test_dispatch_to_fleet_defaults_department_to_assistant(self, monkeypatch):
        """No department given falls back to 'assistant' as the agent_id."""

        def fake_dispatch(prompt, agent_id=None, priority="normal", **kwargs):
            assert agent_id == "assistant"
            assert priority == "normal"
            return {"ok": True, "task_id": "jev-00000000", "agent_id": "assistant"}

        monkeypatch.setattr(cli, "dispatch_prompt_to_fleet", fake_dispatch)
        result = cli.dispatch_to_fleet("hello")
        assert result["ok"] is True

    def test_dispatch_to_fleet_returns_error_on_failure(self, monkeypatch):
        """Exceptions from the dispatcher are caught and returned as errors."""

        def fake_dispatch(prompt, agent_id=None, priority="normal", **kwargs):
            raise RuntimeError("hive dir unwritable")

        monkeypatch.setattr(cli, "dispatch_prompt_to_fleet", fake_dispatch)
        result = cli.dispatch_to_fleet("hello")
        assert result == {"ok": False, "error": "hive dir unwritable"}


class TestSiriBridge:
    """Tests for Siri shortcut bridge."""

    def test_siri_bridge_exists(self):
        """siri_dost.sh exists in dost directory."""
        script = Path(__file__).resolve().parents[1] / "siri_dost.sh"
        assert script.exists()


class TestVoiceCLI:
    """Tests for voice CLI entry point."""

    def test_cli_sanitizes_spoken_response(self, monkeypatch, capsys):
        """Spoken reply must not leak model/pool/task_id metadata."""
        with patch("voice.cli.dost_respond") as mock_respond:
            mock_respond.return_value = (
                "Done. model=qwen3 pool=free_local task_id=jev-abcd1234 "
                "agent_id=general-assistant"
            )
            with patch("voice.cli.synthesize") as mock_tts:
                mock_tts.return_value = None
                with patch("voice.cli.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    cli.main(["research AAPL earnings"])
                    spoken = mock_tts.call_args[0][0]
                    assert "model=" not in spoken
                    assert "pool=" not in spoken
                    assert "task_id=" not in spoken
                    assert "jev-abcd1234" not in spoken
                    assert "agent_id=" not in spoken

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


class TestDispatchCLI:
    """Tests for the --dispatch fleet path on the voice CLI."""

    def test_dispatch_mode_prints_task_id_and_speaks_result(
        self, monkeypatch, capsys
    ):
        """--dispatch prints task_id JSON, speaks the fleet result, records the turn."""
        calls = []

        def fake_dispatch(prompt, agent_id=None, priority="normal", **kwargs):
            calls.append((prompt, agent_id, priority))
            return {"ok": True, "task_id": "jev-abcd1234", "agent_id": "research"}

        def fake_wait(task_id, timeout_sec=20):
            return {"status": "done", "result": {"text": "AAPL research complete."}}

        recorded = []

        def fake_append(conversation_id, interface, user, response):
            recorded.append((conversation_id, interface, user, response))

        monkeypatch.setattr(cli, "dispatch_prompt_to_fleet", fake_dispatch)
        monkeypatch.setattr(cli, "_wait_for_task", fake_wait)
        monkeypatch.setattr("jarvis_memory.session.append_turn", fake_append)
        with patch("voice.cli.synthesize") as mock_tts:
            mock_tts.return_value = None
            with patch("voice.cli.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = cli.main(["--dispatch", "research AAPL earnings"])

        assert result == 0
        assert calls == [("research AAPL earnings", "assistant", "normal")]
        out = capsys.readouterr().out
        assert '"task_id": "jev-abcd1234"' in out
        mock_tts.assert_called_once()
        spoken = mock_tts.call_args[0][0]
        assert "jev-abcd1234" not in spoken
        assert "AAPL research complete" in spoken
        assert recorded == [("voice-owner", "voice", "research AAPL earnings", spoken)]

    def test_dispatch_mode_failure_prints_error(self, monkeypatch, capsys):
        """Failed dispatch prints error JSON and exits non-zero."""

        def fake_dispatch(prompt, agent_id=None, priority="normal", **kwargs):
            return {"ok": False, "error": "hive dir unwritable"}

        monkeypatch.setattr(cli, "dispatch_prompt_to_fleet", fake_dispatch)
        with patch("voice.cli.synthesize") as mock_tts:
            mock_tts.return_value = None
            with patch("voice.cli.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = cli.main(["--dispatch", "hello"])

        assert result == 1
        out = capsys.readouterr().out
        assert '"ok": false' in out
        mock_tts.assert_called_once()


class TestSessionPersistence:
    """Tests for jarvis_memory.session load/save roundtrip (no real disk writes)."""

    def test_append_then_load_roundtrip(self, monkeypatch):
        """Turns appended via append_turn are readable back via load_session."""

        class FakeSession:
            def __init__(self, cid):
                self.id = cid
                self.interface = "voice"
                self.user_id = None
                self.created_at = ""
                self.updated_at = ""
                self.messages = []
                self.metadata = {}

        class FakeMemory:
            def __init__(self):
                self.sessions = {}

            def load_session(self, conversation_id):
                return self.sessions.get(conversation_id)

            def create_session(self, conversation_id, interface="voice", user_id=None):
                session = FakeSession(conversation_id)
                self.sessions[conversation_id] = session
                return session

            def save_session(self, session):
                self.sessions[session.id] = session

            def record_turn(self, conversation_id, interface, user, response):
                session = self.load_session(conversation_id) or self.create_session(
                    conversation_id, interface=interface
                )
                session.messages.extend(
                    [
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": response},
                    ]
                )
                self.save_session(session)

        _fake_memory = FakeMemory()
        monkeypatch.setattr(
            "jarvis_memory.session.get_unified_memory", lambda: _fake_memory
        )

        from jarvis_memory import session as session_mod

        session_mod.append_turn("voice-1", "voice", "research AAPL", "AAPL result")
        session_mod.append_turn(
            "voice-1", "voice", "what was I researching?", "You were researching AAPL."
        )

        loaded = session_mod.load_session("voice-1")
        assert loaded is not None
        assert loaded["conversation_id"] == "voice-1"
        texts = [m["content"] for m in loaded["messages"]]
        assert "research AAPL" in texts
        assert "what was I researching?" in texts
        assert "You were researching AAPL." in texts


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))