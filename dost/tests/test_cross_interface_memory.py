"""Cross-interface memory recall tests for dost.

Verifies that a fact set via one interface (CLI) is recallable via another
(voice), using the same conversation_id, and that different conversation_ids
stay isolated. These are the properties that make dost "top class" — an
assistant that remembers what you said, no matter how you spoke to it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dost import dost_main
from memory_pkg.unified import UnifiedMemory


def make_memory(tmp_path) -> UnifiedMemory:
    return UnifiedMemory(
        "cross-interface-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )


def stub_companion(monkeypatch, memory):
    monkeypatch.setattr(dost_main, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(dost_main, "build_context", lambda: "LIVE CONTEXT")
    monkeypatch.setattr(dost_main, "wants_audit", lambda task: False)
    monkeypatch.setattr(dost_main.MEMORY, "add_interaction", lambda *args, **kwargs: None)


def fake_decide_returns(task, context, style=""):
    """LLM decides: conversational, echoes back with a memory-aware nod."""
    return f"I heard you: {task}"


def test_voice_recalls_fact_set_via_cli(tmp_path, monkeypatch):
    """A preference stated via CLI is recalled when asked via voice interface."""
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)
    monkeypatch.setattr(dost_main, "llm_decide", fake_decide_returns)

    # Turn 1 via CLI: user states a preference.
    reply1 = dost_main.dost_respond(
        "I prefer concise replies.",
        conversation_id="shared-conv-1",
        interface="cli",
    )
    assert "I heard you: I prefer concise replies." in reply1

    # Turn 2 via voice: follow-up must see the CLI turn via injected memory.
    context_captured = {}

    def capturing_decide(task, context, style=""):
        context_captured["context"] = context
        return f"I heard you: {task}"

    monkeypatch.setattr(dost_main, "llm_decide", capturing_decide)
    dost_main.dost_respond(
        "What do I prefer?",
        conversation_id="shared-conv-1",
        interface="voice",
    )
    assert "I prefer concise replies." in context_captured["context"]

    # The voice response itself should also reflect the memory.
    session = memory.load_session("shared-conv-1")
    assert session is not None
    # Both interfaces' turns are present in the same session.
    messages = [m["content"] for m in session.messages]
    assert "I prefer concise replies." in messages
    assert "What do I prefer?" in messages


def test_different_conversation_ids_stay_isolated(tmp_path, monkeypatch):
    """A fact in one conversation_id must not leak into another."""
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)
    monkeypatch.setattr(dost_main, "llm_decide", fake_decide_returns)

    dost_main.dost_respond(
        "I prefer concise replies.",
        conversation_id="conv-a",
        interface="cli",
    )

    context_captured = {}

    def capturing_decide(task, context, style=""):
        context_captured["context"] = context
        return f"I heard you: {task}"

    monkeypatch.setattr(dost_main, "llm_decide", capturing_decide)
    dost_main.dost_respond(
        "What do I prefer?",
        conversation_id="conv-b",
        interface="voice",
    )
    assert "I prefer concise replies." not in context_captured["context"]


def test_memory_persists_across_restart(tmp_path):
    """A fact recorded in one UnifiedMemory instance survives a fresh instance
    pointed at the same storage dirs (simulating a process restart)."""
    memory = make_memory(tmp_path)
    memory.record_turn("conv-persist", "cli", "I prefer concise replies.", "Noted.")

    # Simulate restart: brand-new UnifiedMemory instance, same storage dirs.
    restarted = make_memory(tmp_path)
    session = restarted.load_session("conv-persist")
    assert session is not None
    messages = [m["content"] for m in session.messages]
    assert "I prefer concise replies." in messages
    assert "Noted." in messages

    # Facts also survive the restart.
    facts = restarted.get_facts("conv-persist")
    assert [(f.type, f.content) for f in facts] == [("preference", "concise replies")]


def test_interface_history_tracks_hops(tmp_path):
    """Moving across interfaces records each hop in interface_history."""
    memory = make_memory(tmp_path)
    memory.record_turn("conv-hops", "web", "Hello", "Hi there.")
    memory.record_turn("conv-hops", "telegram", "What next?", "We can review the fleet.")
    memory.record_turn("conv-hops", "voice", "Bye for now.", "Talk soon.")

    session = memory.load_session("conv-hops")
    assert session is not None
    hops = session.interface_history
    assert len(hops) == 2
    assert hops[0]["from_interface"] == "web"
    assert hops[0]["to_interface"] == "telegram"
    assert hops[1]["from_interface"] == "telegram"
    assert hops[1]["to_interface"] == "voice"
    assert session.interface == "voice"
