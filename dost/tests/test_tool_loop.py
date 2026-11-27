"""Tests for the Claude-like tool-use loop in dost_respond.

Verifies that dost_respond iterates: LLM picks a research tool, the tool runs,
the result is fed back, and the LLM produces a final answer — capped at
TOOL_LOOP_MAX_STEPS so a turn always terminates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dost import dost_main
from memory_pkg.unified import UnifiedMemory


def make_memory(tmp_path):
    return UnifiedMemory(
        "tool-loop-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )


def stub_companion(monkeypatch, memory):
    monkeypatch.setattr(dost_main, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(dost_main, "build_context", lambda: "LIVE CONTEXT")
    monkeypatch.setattr(dost_main, "wants_audit", lambda task: False)
    monkeypatch.setattr(dost_main, "_conversation_prefix", lambda conversation_id: "")
    monkeypatch.setattr(dost_main.MEMORY, "add_interaction", lambda *args, **kwargs: None)


def test_tool_loop_executes_search_then_answers(monkeypatch, tmp_path):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)

    decisions = iter([
        "COMMAND:web_search NSE RELIANCE news",
        "Based on the latest results, RELIANCE is trading higher.",
    ])

    def fake_decide(task, context, style=""):
        return next(decisions)

    search_calls = []

    def fake_run_web_search(query):
        search_calls.append(query)
        return "Web results for 'NSE RELIANCE news': - RELIANCE up 2% (https://example.com)"

    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "run_web_search", fake_run_web_search)

    reply = dost_main.dost_respond(
        "what's happening with RELIANCE?",
        conversation_id="conv-1",
        interface="cli",
    )

    assert search_calls == ["NSE RELIANCE news"]
    assert "Based on the latest results, RELIANCE is trading higher." in reply


def test_tool_loop_fleet_dispatch_then_answers(monkeypatch, tmp_path):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)

    decisions = iter([
        "FLEET:Analyze the latest NSE market data",
        "The fleet analysis shows mixed signals across sectors.",
    ])

    def fake_decide(task, context, style=""):
        return next(decisions)

    dispatched = []

    def fake_dispatch(prompt, agent_id=None, priority="normal", parent_task_id=None,
                      dry_run=False, chain=None, workspace_id=None, debug=False):
        dispatched.append((prompt, parent_task_id))
        return {"ok": True, "task_id": "jev-fleet-123"}

    def fake_wait_for_task(task_id, timeout_sec=20):
        return {"status": "done", "result": {"text": "Fleet analysis complete: NSE breadth is positive."}}

    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "dispatch_prompt_to_fleet", fake_dispatch)
    monkeypatch.setattr(dost_main, "_wait_for_task", fake_wait_for_task)

    reply = dost_main.dost_respond(
        "analyze the market",
        conversation_id="conv-3",
        interface="cli",
    )

    assert len(dispatched) == 1
    assert dispatched[0][0] == "Analyze the latest NSE market data"
    assert "The fleet analysis shows mixed signals across sectors." in reply


def test_tool_loop_orchestrate_then_answers(monkeypatch, tmp_path):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)

    decisions = iter([
        "ORCHESTRATE:Research RELIANCE earnings and summarize",
        "RELIANCE earnings beat expectations across all segments.",
    ])

    def fake_decide(task, context, style=""):
        return next(decisions)

    orchestrated = []

    def fake_orchestrate(goal, conversation_id="cli-default", interface="cli", debug=False):
        orchestrated.append(goal)
        return "Orchestrated result: RELIANCE earnings summary."

    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "orchestrate", fake_orchestrate)

    reply = dost_main.dost_respond(
        "research RELIANCE earnings",
        conversation_id="conv-4",
        interface="cli",
    )

    assert orchestrated == ["Research RELIANCE earnings and summarize"]
    assert "RELIANCE earnings beat expectations across all segments." in reply


def test_tool_loop_respects_step_cap(monkeypatch, tmp_path):
    memory = make_memory(tmp_path)
    stub_companion(monkeypatch, memory)

    def fake_decide(task, context, style=""):
        return "COMMAND:web_search some query"

    search_calls = []

    def fake_run_web_search(query):
        search_calls.append(query)
        return "search result text"

    narrated = {}

    def fake_narrate(command, output, context):
        narrated["command"] = command
        return "Narrated result."

    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "run_web_search", fake_run_web_search)
    monkeypatch.setattr(dost_main, "llm_narrate", fake_narrate)

    reply = dost_main.dost_respond(
        "do research",
        conversation_id="conv-2",
        interface="cli",
    )

    assert len(search_calls) == dost_main.TOOL_LOOP_MAX_STEPS
    assert narrated["command"] == "web_search some query"
    assert "Narrated result." in reply
