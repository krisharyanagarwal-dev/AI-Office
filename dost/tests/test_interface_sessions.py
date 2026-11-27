"""Cross-interface session continuity and HTTP safety tests."""

from __future__ import annotations

import http.client
import json
import sys
import threading
import urllib.request
from pathlib import Path

from dost import dost_main
from dost.bots import telegram_bot
from dost.chat_core import ChatStore, DostChatServer, Handler
from dost.memory_pkg.unified import UnifiedMemory
from voice import voice_cli


def make_memory(tmp_path) -> UnifiedMemory:
    return UnifiedMemory(
        "interface-session-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )


def stub_companion(monkeypatch, memory):
    monkeypatch.setattr(dost_main, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(dost_main, "build_context", lambda: "LIVE CONTEXT")
    monkeypatch.setattr(dost_main, "wants_audit", lambda task: False)
    monkeypatch.setattr(dost_main, "llm_decide", lambda task, context, style="": "Noted.")
    monkeypatch.setattr(dost_main.MEMORY, "add_interaction", lambda *args, **kwargs: None)
    # check_fleet_health makes live network calls; stub it for deterministic tests.
    monkeypatch.setattr("ops.proactive_monitor.check_fleet_health", lambda: [])


class SessionEchoHandler(Handler):
    def answer(self, text, history, backend, session_id="default"):
        return f"{session_id}:{text}"


def test_http_chat_passes_session_id_to_handler(tmp_path):
    store = ChatStore(tmp_path / "chats")
    server = DostChatServer(("127.0.0.1", 0), SessionEchoHandler, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/chat",
            data=json.dumps({"text": "hello", "session_id": "session-42"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["reply"] == "session-42:hello"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_sse_stream_sends_content_and_closes(tmp_path):
    store = ChatStore(tmp_path / "chats")
    server = DostChatServer(("127.0.0.1", 0), SessionEchoHandler, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "POST",
            "/api/chat/stream",
            body=json.dumps({"text": "hello", "session_id": "session-sse"}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read().decode()
        assert response.getheader("Connection") == "close"
        assert '"text": "session-sse:hello"' in body
        assert '"reply": "session-sse:hello"' in body
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_chat_store_rejects_path_traversal(tmp_path):
    store = ChatStore(tmp_path / "chats")

    try:
        store.path("../outside")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe session ID was accepted")


def test_telegram_reply_uses_per_chat_memory(tmp_path, monkeypatch):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)

    body, voice_path = telegram_bot._dost_reply("I prefer concise replies.", 42)

    assert body == "Noted."
    assert voice_path is None
    session = memory.load_session("telegram-42")
    assert session is not None
    assert session.messages[-2]["content"] == "I prefer concise replies."
    assert session.messages[-1]["content"] == "Noted."


def test_voice_cli_uses_shared_owner_memory(tmp_path, monkeypatch):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)
    monkeypatch.setattr(voice_cli, "record_audio", lambda duration, path: True)
    monkeypatch.setattr(
        voice_cli,
        "speech_to_text",
        lambda path: {"ok": True, "text": "I prefer concise replies.", "provider": "test"},
    )
    monkeypatch.setattr(
        voice_cli,
        "text_to_speech",
        lambda text: {"ok": True, "path": str(tmp_path / "reply.mp3")},
    )
    monkeypatch.setattr(voice_cli, "play_audio", lambda path: None)

    transcript = voice_cli.run_once(1)

    assert transcript == "I prefer concise replies."
    session = memory.load_session("voice-owner")
    assert session is not None
    assert session.messages[-2]["content"] == "I prefer concise replies."
    assert session.messages[-1]["content"] == "Noted."


def test_cli_message_uses_shared_memory(tmp_path, monkeypatch, capsys):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)
    monkeypatch.setattr(sys, "argv", ["dost", "I prefer concise replies."])

    dost_main.main()

    assert "Noted." in capsys.readouterr().out
    session = memory.load_session("cli-default")
    assert session is not None
    assert session.messages[-2]["content"] == "I prefer concise replies."
    assert session.messages[-1]["content"] == "Noted."


def test_dost_respond_remembers_across_calls(tmp_path, monkeypatch):
    memory = make_memory(tmp_path)
    captured = {}

    def fake_decide(task, context, style=""):
        captured["context"] = context
        return "You prefer concise replies."

    monkeypatch.setattr(dost_main, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(dost_main, "build_context", lambda: "LIVE CONTEXT")
    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "wants_audit", lambda task: False)
    # _conversation_prefix now scopes per conversation_id; bypass it so the
    # only cross-session memory source under test is build_context_prompt.
    monkeypatch.setattr(dost_main, "_conversation_prefix", lambda conversation_id: "")
    monkeypatch.setattr(dost_main.MEMORY, "add_interaction", lambda *args, **kwargs: None)

    # First turn: user states a preference; turn + extracted fact must persist.
    reply1 = dost_main.dost_respond(
        "I prefer concise replies.",
        conversation_id="conv-dost-1",
        interface="cli",
    )
    assert "You prefer concise replies." in reply1
    session = memory.load_session("conv-dost-1")
    assert session is not None
    assert session.messages[-2]["content"] == "I prefer concise replies."
    assert "You prefer concise replies." in session.messages[-1]["content"]
    facts = memory.get_facts("conv-dost-1")
    assert ("preference", "concise replies") in [(f.type, f.content) for f in facts]

    # Second turn: follow-up must see the earlier turn via injected memory context.
    dost_main.dost_respond(
        "What do I prefer?",
        conversation_id="conv-dost-1",
        interface="cli",
    )
    assert "I prefer concise replies." in captured["context"]

    # A separate conversation must not leak into this one.
    dost_main.dost_respond("Hello.", conversation_id="conv-dost-2", interface="cli")
    assert "I prefer concise replies." not in captured["context"]
