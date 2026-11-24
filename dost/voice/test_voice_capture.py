"""Tests for natural speech endpoint detection in the Mac voice CLI."""

from __future__ import annotations

import io
import struct
import wave
from types import SimpleNamespace

from voice import voice_cli


SAMPLE_RATE = 16000
FRAME_SAMPLES = 320  # 20 ms of mono PCM16


def pcm_frame(amplitude: int) -> bytes:
    return struct.pack("<h", amplitude) * FRAME_SAMPLES


def test_initial_silence_does_not_end_recording():
    detector = voice_cli.SpeechEndDetector(sample_rate=SAMPLE_RATE)

    for _ in range(100):
        assert detector.feed(pcm_frame(0)) is False


def test_recording_ends_after_speech_and_required_silence():
    detector = voice_cli.SpeechEndDetector(sample_rate=SAMPLE_RATE, silence_seconds=0.8)

    for _ in range(20):
        assert detector.feed(pcm_frame(2000)) is False
    for _ in range(39):
        assert detector.feed(pcm_frame(0)) is False
    assert detector.feed(pcm_frame(0)) is True


def test_speech_during_pause_resets_silence_timer():
    detector = voice_cli.SpeechEndDetector(sample_rate=SAMPLE_RATE, silence_seconds=0.4)

    for _ in range(20):
        detector.feed(pcm_frame(2000))
    for _ in range(15):
        assert detector.feed(pcm_frame(0)) is False
    assert detector.feed(pcm_frame(2000)) is False
    for _ in range(19):
        assert detector.feed(pcm_frame(0)) is False
    assert detector.feed(pcm_frame(0)) is True


def test_short_noise_blip_is_not_treated_as_complete_speech():
    detector = voice_cli.SpeechEndDetector(
        sample_rate=SAMPLE_RATE,
        silence_seconds=0.4,
        min_speech_seconds=0.25,
    )

    assert detector.feed(pcm_frame(2000)) is False
    for _ in range(30):
        assert detector.feed(pcm_frame(0)) is False


class FakeCaptureProcess:
    def __init__(self, audio: bytes):
        self.stdout = io.BytesIO(audio)
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def communicate(self, timeout=None):
        return b"", b""


def test_record_audio_writes_pcm_and_stops_at_natural_pause(tmp_path, monkeypatch):
    audio = pcm_frame(2000) * 20 + pcm_frame(0) * 40
    process = FakeCaptureProcess(audio)
    monkeypatch.setattr(
        voice_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="fixed duration"),
    )
    monkeypatch.setattr(voice_cli.subprocess, "Popen", lambda *args, **kwargs: process)
    output = tmp_path / "capture.wav"

    assert voice_cli.record_audio(15, str(output)) is True
    assert process.terminated is True
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.getnchannels() == 1
        assert wav.getnframes() == len(audio) // 2
