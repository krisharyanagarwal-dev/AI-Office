"""Tests that PetHandler chat routes through dost_respond's tool-use loop.

The default ("dost") backend on /api/chat and /api/chat/stream now runs
dost_respond so web chat gets web_search / fleet / orchestrate tool iteration.
JARVIS mode, explicit ":backend" model requests, and openclaw are untouched.
"""

from __future__ import annotations

import pytest

from dost.pet_server import PetHandler


def _handler():
    # BaseHTTPRequestHandler.__init__ parses a socket; we only call the
    # answer/stream_answer methods, which never touch self.
    return PetHandler.__new__(PetHandler)


def test_stream_answer_chunks_dost_respond_output(monkeypatch):
    captured = {}

    def fake_dost_respond(
        task, department=None, conversation_id="cli-default", interface="cli"
    ):
        captured["args"] = (task, conversation_id, interface)
        return "First chunk. Second chunk."

    monkeypatch.setattr("dost.pet_server.dost_respond", fake_dost_respond)

    chunks = list(_handler().stream_answer("what's happening with RELIANCE?", [], "dost", "sess-1"))

    assert captured["args"] == ("what's happening with RELIANCE?", "web-sess-1", "web")
    assert all(c["type"] == "text" for c in chunks)
    assert "".join(c["text"] for c in chunks) == "First chunk. Second chunk."


def test_answer_returns_dost_respond_output(monkeypatch):
    monkeypatch.setattr(
        "dost.pet_server.dost_respond",
        lambda task, department=None, conversation_id="cli-default", interface="cli": "web answer.",
    )
    assert _handler().answer("hi", [], "dost", "sess-2") == "web answer."


def test_stream_answer_falls_back_to_companion_when_dost_respond_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("dost.pet_server.dost_respond", boom)
    monkeypatch.setattr(
        "dost.pet_server.companion_respond",
        lambda task, conversation_id=None, interface="web", history=None: "companion fallback",
    )

    chunks = list(_handler().stream_answer("hello", [], "dost", "sess-3"))
    assert chunks == [{"type": "text", "text": "companion fallback"}]


def test_answer_falls_back_to_companion_when_dost_respond_fails(monkeypatch):
    monkeypatch.setattr("dost.pet_server.dost_respond", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(
        "dost.pet_server.companion_respond",
        lambda task, conversation_id=None, interface="web", history=None: "fb",
    )
    assert _handler().answer("hi", [], "dost", "sess-4") == "fb"


def test_answer_uses_companion_fallback_when_dost_respond_empty(monkeypatch):
    monkeypatch.setattr("dost.pet_server.dost_respond", lambda *a, **k: "")
    monkeypatch.setattr(
        "dost.pet_server.companion_respond",
        lambda task, conversation_id=None, interface="web", history=None: "fb",
    )
    assert _handler().answer("hi", [], "dost", "sess-5") == "fb"


def test_explicit_backend_and_jarvis_paths_stay_untouched(monkeypatch):
    calls = []

    def fake_ask_model(backend, text, history):
        calls.append(backend)
        return {"error": "", "reply": "model reply", "label": "m", "ms": 5}

    monkeypatch.setattr("dost.pet_server.models.ask_model", fake_ask_model)

    assert _handler().answer("hi", [], "openai:gpt-4", "sess-6") == "model reply"
    assert calls == ["openai:gpt-4"]

