"""Tests for the Dost broadcast path: one prompt to every worker, answers remembered.

Paper-only: no provider calls, no live orders. HIVE_DIR, BROADCAST_DIR and the
memory store are redirected to temp locations / a fake, so nothing touches the
real fleet hive or the real UnifiedMemory.

Run: python -m pytest dost/tests/test_broadcast.py -q   (from AI-Office/)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import dost_main as dm  # noqa: E402

ROSTER = ["alpha-analyst", "beta-trader", "gamma-risk"]


class FakeMemory:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str, str, str]] = []
        self.work_results: list[dict] = []

    def record_turn(self, conversation_id, interface, user_message, dost_response):
        self.turns.append((conversation_id, interface, user_message, dost_response))

    def add_work_result(self, content, source, conversation_id, metadata=None):
        self.work_results.append({"content": content, "conversation_id": conversation_id, "metadata": metadata or {}})

    def build_context_prompt(self, conversation_id, user_message):
        return ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    hive.mkdir()
    monkeypatch.setattr(dm, "HIVE_DIR", hive)
    monkeypatch.setattr(dm, "BROADCAST_DIR", tmp_path / "broadcasts")
    monkeypatch.setattr(dm, "fleet_roster", lambda: list(ROSTER))
    fake = FakeMemory()
    monkeypatch.setattr(dm, "get_unified_memory", lambda *a, **k: fake)
    return {"hive": hive, "memory": fake}


def _task_files(hive: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(hive.glob("*.json"))]


def test_dry_run_targets_every_worker_and_writes_nothing(env):
    result = dm.dispatch_broadcast_to_fleet("status check", dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert sorted(result["task_ids"]) == sorted(ROSTER)
    assert _task_files(env["hive"]) == []
    assert env["memory"].turns == []


def test_real_broadcast_writes_one_tagged_task_per_worker(env):
    result = dm.dispatch_broadcast_to_fleet("status check")

    assert result["ok"] is True
    assert result["dispatched"] == len(ROSTER)
    tasks = _task_files(env["hive"])
    assert sorted(t["agent_id"] for t in tasks) == sorted(ROSTER)
    assert {t["metadata"]["broadcast_id"] for t in tasks} == {result["broadcast_id"]}
    assert all(t["description"] == "status check" for t in tasks)

    manifest = json.loads((dm.BROADCAST_DIR / f"{result['broadcast_id']}.json").read_text())
    assert manifest["prompt"] == "status check"
    assert sorted(manifest["workers"]) == sorted(ROSTER)
    assert manifest["recorded"] == []


def test_narrowing_to_agents_only_targets_those(env):
    result = dm.dispatch_broadcast_to_fleet("ping", agents=["beta-trader", "beta-trader", "gamma-risk"])

    assert result["total"] == 2  # duplicate removed
    assert sorted(t["agent_id"] for t in _task_files(env["hive"])) == ["beta-trader", "gamma-risk"]


def test_overlong_prompt_is_refused_without_writing(env):
    result = dm.dispatch_broadcast_to_fleet("x" * (dm.MAX_DISPATCH_PROMPT_LEN + 1))

    assert result["ok"] is False
    assert _task_files(env["hive"]) == []


def test_status_records_each_finished_answer_once(env):
    sent = dm.dispatch_broadcast_to_fleet("what is the risk?")
    bid = sent["broadcast_id"]
    ids = sent["task_ids"]

    # Simulate the dispatcher finishing two workers: one done, one errored.
    def finish(agent, status, **extra):
        path = env["hive"] / f"{ids[agent]}.json"
        task = json.loads(path.read_text())
        task["status"] = status
        task.update(extra)
        path.write_text(json.dumps(task))

    finish("alpha-analyst", "done", result={"text": "Risk is moderate."})
    finish("beta-trader", "error", error="provider timeout")

    first = dm.broadcast_status(bid)
    assert first["ok"] is True
    assert first["counts"] == {"done": 1, "error": 1, "pending": 1, "missing": 0}
    assert sorted(first["newly_recorded"]) == ["alpha-analyst", "beta-trader"]
    # 1 dispatch summary (written at send time) + 2 worker answers.
    assert len(env["memory"].turns) == 3
    assert env["memory"].turns[0][0] == f"broadcast-{bid}"
    assert any("Risk is moderate." in t[3] for t in env["memory"].turns)
    assert any("provider timeout" in t[3] for t in env["memory"].turns)

    # A second status check must not record the same workers again.
    second = dm.broadcast_status(bid)
    assert second["newly_recorded"] == []
    assert len(env["memory"].turns) == 3

    # Work results: 1 dispatch summary + 2 worker answers, each recallable later.
    assert len(env["memory"].work_results) == 3
    answers = [w["content"] for w in env["memory"].work_results]
    assert any("alpha-analyst" in c and "Risk is moderate." in c for c in answers)
    assert any("beta-trader" in c and "provider timeout" in c for c in answers)


def test_status_for_unknown_broadcast_reports_error(env):
    result = dm.broadcast_status("bc-doesnotexist")
    assert result["ok"] is False
    assert "No broadcast" in result["error"]


def test_dispatch_prompt_extra_metadata_is_merged(env):
    res = dm.dispatch_prompt_to_fleet("hi", agent_id="alpha-analyst", extra_metadata={"broadcast_id": "bc-test"})
    assert res["ok"] is True
    task = json.loads((env["hive"] / f"{res['task_id']}.json").read_text())
    assert task["metadata"]["broadcast_id"] == "bc-test"
    assert task["metadata"]["source"] == "dost"


def test_saved_work_is_recalled_from_a_brand_new_conversation(tmp_path):
    from memory_pkg.unified import UnifiedMemory

    mem = UnifiedMemory("test", jarvis_dir=tmp_path / "jarvis", memory_dir=tmp_path / "mem")
    mem.add_work_result(
        'Worker risk-manager answered broadcast question "is the book safe": Yes, within limits.',
        source="fleet",
        conversation_id="broadcast-bc-1",
    )

    context = mem.build_context_prompt("brand-new-chat", "what did the risk workers say about the book?")
    assert "Saved Work Results" in context
    assert "within limits" in context
    assert "Current Query" in context


def test_unrelated_query_with_no_history_is_passed_through_unchanged(tmp_path):
    from memory_pkg.unified import UnifiedMemory

    mem = UnifiedMemory("test", jarvis_dir=tmp_path / "jarvis", memory_dir=tmp_path / "mem")
    mem.add_work_result("Worker risk-manager answered: within limits.", source="fleet", conversation_id="b")

    assert mem.build_context_prompt("brand-new-chat", "hello there") == "hello there"


# --- Worker selection: the bot proposes a relevant subset -------------------

def _fake_chat(reply):
    return lambda messages, temperature=0.0, max_tokens=0: reply


def test_select_broadcast_workers_uses_llm_pick(monkeypatch):
    monkeypatch.setattr(dm, "_chat", _fake_chat({"text": '["beta-trader", "gamma-risk"]'}))

    picked = dm.select_broadcast_workers("who should check risk?", ROSTER)

    assert picked == ["beta-trader", "gamma-risk"]


def test_select_broadcast_workers_drops_invalid_ids_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        dm, "_chat",
        _fake_chat({"text": '["beta-trader", "nobody", "beta-trader", "alpha-analyst"]'}),
    )

    picked = dm.select_broadcast_workers("q", ROSTER)

    assert picked == ["beta-trader", "alpha-analyst"]


@pytest.mark.parametrize("reply", [None, {"text": "sorry, no idea"}, {"text": "[]"}])
def test_select_broadcast_workers_falls_back_to_full_roster(monkeypatch, reply):
    monkeypatch.setattr(dm, "_chat", _fake_chat(reply))

    assert dm.select_broadcast_workers("q", ROSTER) == ROSTER


def test_select_broadcast_workers_all_invalid_falls_back(monkeypatch):
    monkeypatch.setattr(dm, "_chat", _fake_chat({"text": '["ghost-worker"]'}))

    assert dm.select_broadcast_workers("q", ROSTER) == ROSTER


def test_cli_pick_shows_proposal_and_writes_nothing(env, monkeypatch, capsys):
    monkeypatch.setattr(dm, "_chat", _fake_chat({"text": '["beta-trader", "gamma-risk"]'}))
    monkeypatch.setattr(dm, "ensure_default_workspace", lambda: "ws-test")
    monkeypatch.setattr(sys, "argv", ["dost", "--broadcast", "who checks risk?", "--pick"])

    dm.main()

    proposal = json.loads(capsys.readouterr().out)
    assert proposal["proposed_workers"] == ["beta-trader", "gamma-risk"]
    assert proposal["requires_confirmation"] is True
    assert _task_files(env["hive"]) == []
    assert not dm.BROADCAST_DIR.exists()


def test_cli_pick_send_requires_confirm(env, monkeypatch, capsys):
    monkeypatch.setattr(dm, "_chat", _fake_chat({"text": '["beta-trader", "gamma-risk"]'}))
    monkeypatch.setattr(dm, "ensure_default_workspace", lambda: "ws-test")

    monkeypatch.setattr(sys, "argv", ["dost", "--broadcast", "who checks risk?", "--pick"])
    dm.main()
    capsys.readouterr()
    assert _task_files(env["hive"]) == []

    monkeypatch.setattr(sys, "argv", ["dost", "--broadcast", "who checks risk?", "--pick", "--confirm"])
    dm.main()
    result = json.loads(capsys.readouterr().out)

    assert result["ok"] is True
    assert sorted(t["agent_id"] for t in _task_files(env["hive"])) == ["beta-trader", "gamma-risk"]


def test_chat_broadcast_proposes_then_sends_only_on_confirmation(env, monkeypatch):
    monkeypatch.setattr(dm, "build_context", lambda: "")
    monkeypatch.setattr(dm, "dost_greeting", lambda: "")
    monkeypatch.setattr(dm, "_conversation_prefix", lambda conversation_id: "")
    monkeypatch.setattr(dm, "_chat", _fake_chat({"text": '["beta-trader", "gamma-risk"]'}))
    monkeypatch.setattr(dm, "llm_decide", lambda task, context, style="": "BROADCAST: who checks risk?")
    monkeypatch.setattr(dm.MEMORY, "add_interaction", lambda *a, **k: None)

    first = dm.dost_respond("broadcast this: who checks risk?", conversation_id="chat-broadcast-test")
    assert "beta-trader" in first
    assert "gamma-risk" in first
    assert "alpha-analyst" not in first
    assert _task_files(env["hive"]) == []

    second = dm.dost_respond("yes", conversation_id="chat-broadcast-test")
    assert "Sent to 2" in second
    assert sorted(t["agent_id"] for t in _task_files(env["hive"])) == ["beta-trader", "gamma-risk"]
    assert not dm._pending_path("chat-broadcast-test").exists()


def test_tier_c_agents_come_from_the_dispatcher_table():
    blocked = dm.tier_c_agents()
    assert "risk-manager" in blocked
    assert "compliance-checker" in blocked
    assert "general-assistant" not in blocked


def test_named_tier_c_agent_is_refused_and_not_dispatched(env):
    result = dm.dispatch_broadcast_to_fleet("hello", agents=["risk-manager", "alpha-analyst"])

    assert result["total"] == 1
    assert result["dispatched"] == 1
    assert "risk-manager" in result["errors"]
    assert sorted(t["agent_id"] for t in _task_files(env["hive"])) == ["alpha-analyst"]


def test_collect_records_each_answer_once_and_reports_open(env):
    sent = dm.dispatch_broadcast_to_fleet("collect me")
    bid = sent["broadcast_id"]

    first = dm.broadcast_collect()
    assert first["open"] == 1
    assert first["newly_recorded"] == {}

    path = env["hive"] / f"{sent['task_ids']['alpha-analyst']}.json"
    task = json.loads(path.read_text())
    task.update(status="done", result={"text": "All quiet."})
    path.write_text(json.dumps(task))

    second = dm.broadcast_collect()
    assert second["newly_recorded"] == {bid: ["alpha-analyst"]}
    third = dm.broadcast_collect()
    assert third["newly_recorded"] == {}


def test_companion_path_proposes_and_confirms_across_interfaces(env, monkeypatch):
    """Pet, Telegram, Slack and Teams all go through companion_respond; a proposal made there must be confirmable."""
    monkeypatch.setattr(dm, "build_context", lambda: "")
    monkeypatch.setattr(dm, "_history_context", lambda history: "")
    monkeypatch.setattr(dm, "select_broadcast_workers", lambda prompt, roster: ["beta-trader"])
    monkeypatch.setattr(dm, "llm_decide", lambda task, context, style="": "BROADCAST: check the book")
    monkeypatch.setattr(dm.MEMORY, "add_interaction", lambda *a, **k: None)

    first = dm.companion_respond("tell all the workers to check the book", conversation_id="telegram-42", interface="telegram")
    assert "beta-trader" in first
    assert _task_files(env["hive"]) == []
    assert dm._pending_path("telegram-42").exists()

    second = dm.companion_respond("yes", conversation_id="telegram-42", interface="telegram")
    assert "Sent to 1" in second
    assert [t["agent_id"] for t in _task_files(env["hive"])] == ["beta-trader"]
    assert not dm._pending_path("telegram-42").exists()


def test_anonymous_chat_still_gets_a_pending_key(env, monkeypatch):
    monkeypatch.setattr(dm, "build_context", lambda: "")
    monkeypatch.setattr(dm, "_history_context", lambda history: "")
    monkeypatch.setattr(dm, "select_broadcast_workers", lambda prompt, roster: ["beta-trader"])
    monkeypatch.setattr(dm, "llm_decide", lambda task, context, style="": "BROADCAST: ping")
    monkeypatch.setattr(dm.MEMORY, "add_interaction", lambda *a, **k: None)

    dm.companion_respond("broadcast ping", conversation_id=None, interface="slack")
    assert dm._pending_path("anon-slack").exists()
    dm._pending_take("anon-slack")
