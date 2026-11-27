"""Behavioral tests for memory-aware, speech-safe Dost conversations."""

from __future__ import annotations

from dost import dost_main
from dost.memory_pkg.unified import UnifiedMemory


def make_memory(tmp_path) -> UnifiedMemory:
    return UnifiedMemory(
        "conversation-quality-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )


def test_response_policy_removes_technical_metadata():
    reply = dost_main.sanitize_response(
        "Done. model=qwen3 pool=free_local task_id=jev-abcd1234 agent_id=general-assistant"
    )

    assert "Done." in reply
    assert "model=" not in reply
    assert "pool=" not in reply
    assert "task_id=" not in reply
    assert "agent_id=" not in reply
    assert "jev-abcd1234" not in reply


def test_response_policy_redacts_secrets_and_provider_names():
    reply = dost_main.sanitize_response(
        "Using Groq with key gsk_abcdefghijklmnopqrstuvwxyz and OpenAI as a fallback."
    )

    assert "Groq" not in reply
    assert "OpenAI" not in reply
    assert "gsk_abcdefghijklmnopqrstuvwxyz" not in reply
    assert "[redacted]" in reply


def test_response_policy_corrects_unsafe_trading_claims():
    reply = dost_main.sanitize_response(
        "The kill switch is unlocked and live orders are enabled."
    )

    assert reply == "The kill switch is locked and live orders remain disabled."


def test_record_turn_persists_messages_and_only_user_facts(tmp_path):
    memory = make_memory(tmp_path)

    memory.record_turn(
        "conv-quality-1",
        "web",
        "I prefer concise replies.",
        "Understood. I must keep that in mind.",
    )

    reloaded = UnifiedMemory(
        "conversation-quality-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )
    session = reloaded.load_session("conv-quality-1")

    assert session is not None
    assert [m["content"] for m in session.messages] == [
        "I prefer concise replies.",
        "Understood. I must keep that in mind.",
    ]
    facts = reloaded.get_facts("conv-quality-1")
    assert [(f.type, f.content) for f in facts] == [
        ("preference", "concise replies")
    ]


def test_record_turn_preserves_history_across_interfaces(tmp_path):
    memory = make_memory(tmp_path)
    memory.record_turn("conv-quality-2", "web", "Hello", "Hi Aryan.")

    reloaded = UnifiedMemory(
        "conversation-quality-test",
        jarvis_dir=tmp_path / "jarvis",
        memory_dir=tmp_path / "memory",
    )
    reloaded.record_turn("conv-quality-2", "telegram", "What next?", "We can review the fleet.")

    session = reloaded.load_session("conv-quality-2")
    assert session is not None
    assert len(session.messages) == 4
    assert session.interface == "telegram"
    assert session.interface_history[-1]["from_interface"] == "web"
    assert session.interface_history[-1]["to_interface"] == "telegram"


def test_record_turn_writes_one_legacy_interaction(tmp_path):
    memory = make_memory(tmp_path)

    memory.record_turn("conv-quality-3", "cli", "Remember this", "I will.")

    from memory_pkg.persistent_memory import ConversationMemory

    legacy = ConversationMemory(
        "conversation-quality-test", memory_dir=tmp_path / "memory"
    ).get_recent_context(limit=10)
    assert len(legacy) == 1
    assert legacy[0]["user_message"] == "Remember this"
    assert legacy[0]["dost_response"] == "I will."


def test_companion_uses_saved_memory_and_records_the_turn(tmp_path, monkeypatch):
    memory = make_memory(tmp_path)
    memory.record_turn("conv-quality-4", "web", "I prefer concise replies.", "Noted.")
    captured = {}

    def fake_decide(task, context, style=""):
        captured["context"] = context
        return "You prefer concise replies."

    monkeypatch.setattr(dost_main, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(dost_main, "build_context", lambda: "LIVE CONTEXT")
    monkeypatch.setattr(dost_main, "llm_decide", fake_decide)
    monkeypatch.setattr(dost_main, "wants_audit", lambda task: False)

    reply = dost_main.companion_respond(
        "What do I prefer?",
        conversation_id="conv-quality-4",
        interface="web",
    )

    assert "I prefer concise replies." in captured["context"]
    assert reply == "You prefer concise replies."
    session = memory.load_session("conv-quality-4")
    assert session is not None
    assert session.messages[-2]["content"] == "What do I prefer?"
    assert session.messages[-1]["content"] == reply


# ---------------------------------------------------------------------------
# Deterministic fallback coverage (Interpretation B: voice reliability when no LLM)
# ---------------------------------------------------------------------------

def test_fallback_decide_maps_research_commands():
    for cmd in ("register", "gate", "holdout", "calibrate", "report", "all"):
        assert dost_main.fallback_decide(cmd, "") == f"COMMAND:{cmd}"


def test_fallback_decide_returns_none_for_conversation():
    assert dost_main.fallback_decide("hello there", "") is None
    assert dost_main.fallback_decide("what do you think?", "") is None


def test_fallback_converse_research_branch():
    reply = dost_main.fallback_converse("research NSE edge", "")
    assert "NSE" in reply or "research" in reply.lower()
    assert "backtest" in reply
    assert "paper-only" in reply.lower() or "cost-aware" in reply.lower()


def test_fallback_converse_trading_branch_paper_only():
    reply = dost_main.fallback_converse("what is my capital?", "")
    assert "paper-only" in reply.lower()
    assert "₹1 lakh" in reply or "₹5L" in reply


def test_fallback_converse_fleet_branch_kill_switch_locked():
    reply = dost_main.fallback_converse("tell me about the fleet", "")
    assert "kill switch is locked" in reply.lower()
    assert "human-only" in reply.lower()


def test_fallback_converse_ops_branch_with_dispatcher(monkeypatch):
    monkeypatch.setattr(
        dost_main, "_fetch_dispatcher_status",
        lambda: {
            "tasks_done": 8, "tasks_created": 10,
            "completion_rate": 80.0, "error_rate": 1.5,
            "error_rate_total": 2.0, "calls_today": 42,
            "pools_available": 3,
        },
    )
    reply = dost_main.fallback_converse("check system health", "")
    assert "8/10 tasks done" in reply
    assert "80%" in reply
    assert "42 calls today" in reply


def test_fallback_converse_ops_branch_without_dispatcher(monkeypatch):
    monkeypatch.setattr(dost_main, "_fetch_dispatcher_status", lambda: None)
    reply = dost_main.fallback_converse("company health", "")
    assert "cost-per-outcome" in reply


def test_fallback_converse_upgrade_branch_tests_first():
    reply = dost_main.fallback_converse("run the upgrade", "")
    assert "tests passing first" in reply


def test_fallback_converse_general_branch():
    reply = dost_main.fallback_converse("write a memo", "")
    assert "code, writing, analysis" in reply


def test_fallback_converse_default_branch():
    reply = dost_main.fallback_converse("something completely random", "")
    assert "I'm your dost" in reply


def test_fallback_narrate_extracts_key_lines():
    output = "net_pnl=1234.56\nconfirmed=true\nsome other line\nfailed=2\nwell-calibrated=9"
    reply = dost_main.fallback_narrate("status", output)
    assert "net_pnl=1234.56" in reply
    assert "confirmed=true" in reply
    assert "failed=2" in reply
    assert "well-calibrated=9" in reply
    assert "some other line" not in reply


def test_fallback_narrate_no_key_lines_echoes_output():
    reply = dost_main.fallback_narrate("status", "just some random output here")
    assert "Here's the output from the status command" in reply
    assert "just some random output here" in reply
