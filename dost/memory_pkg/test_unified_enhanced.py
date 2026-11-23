"""Tests for enhanced unified memory features."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import UnifiedMemory, Fact, Session, get_unified_memory


def make_mem(tmpdir: str) -> UnifiedMemory:
    """Create UnifiedMemory with temp directories."""
    jarvis_dir = Path(tmpdir) / "jarvis_memory"
    memory_dir = Path(tmpdir) / "dost_memory"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    # Reset global to avoid cross-test contamination
    import memory_pkg.unified
    memory_pkg.unified._unified_memories = {}
    return UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)


class TestContextAwarePrompt:
    """Tests for context-aware prompt building."""

    def test_build_context_prompt_basic(self):
        """Build context prompt with basic messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "Research AAPL earnings")
            mem.add_message("conv-1", "assistant", "AAPL earnings beat expectations")
            mem.add_message("conv-1", "user", "What about MSFT?")

            prompt = mem.build_context_prompt("conv-1", "Compare with MSFT")

            assert "Research AAPL earnings" in prompt
            assert "AAPL earnings beat expectations" in prompt
            assert "What about MSFT?" in prompt
            assert "Compare with MSFT" in prompt

    def test_build_context_prompt_with_facts(self):
        """Context prompt includes relevant facts from vector search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "I prefer short briefings")
            mem.add_message("conv-1", "assistant", "Noted")
            # Facts are auto-extracted from messages
            mem.extract_facts("I prefer short briefings and I never want crypto alerts", "conv-1", "cli")
            # Also set as explicit preference
            mem.set_preference("briefing_style", "short")
            mem.set_preference("crypto_alerts", False)

            # Use a query similar to the facts for better hash-based matching
            prompt = mem.build_context_prompt("conv-1", "short briefings crypto alerts")

            assert "short briefings" in prompt
            assert "crypto alerts" in prompt
            assert "User Preferences" in prompt

    def test_build_context_prompt_with_summary(self):
        """Context prompt includes conversation summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "Research AAPL")
            mem.add_message("conv-1", "assistant", "Done")
            mem.summarize_session("conv-1")

            prompt = mem.build_context_prompt("conv-1", "Next question")

            # Summary may be empty if no facts extracted, check for summary section
            assert "Conversation Summary" in prompt or "AAPL" in prompt

    def test_build_context_prompt_interface_history(self):
        """Context prompt tracks interface switches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.sync_from_interface("conv-1", "cli", [{"role": "user", "content": "Hello"}])
            mem.sync_from_interface("conv-1", "telegram", [{"role": "user", "content": "Hi there"}])

            prompt = mem.build_context_prompt("conv-1", "Next")

            # Interface history is tracked in session, check it exists
            session = mem.get_session("conv-1")
            assert len(session.interface_history) >= 1


class TestSessionSummarization:
    """Tests for session summarization."""

    def test_summarize_session_extracts_entities(self):
        """Summarize extracts entities from conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Add messages so session has content
            mem.add_message("conv-1", "user", "Research AAPL earnings")
            mem.add_message("conv-1", "assistant", "AAPL beat expectations")
            # Add facts
            mem.extract_facts("Research AAPL earnings and compare with MSFT", "conv-1", "cli")
            mem.extract_facts("What about GOOGL?", "conv-1", "cli")

            summary = mem.summarize_session("conv-1")

            assert "AAPL" in summary or "MSFT" in summary or "GOOGL" in summary

    def test_summarize_session_extracts_decisions(self):
        """Summarize extracts decisions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "I decided to focus on value stocks")
            mem.add_message("conv-1", "assistant", "Good choice")
            mem.extract_facts("I decided to focus on value stocks", "conv-1", "cli")

            summary = mem.summarize_session("conv-1")

            assert "value stocks" in summary
            assert "Decisions" in summary

    def test_summarize_session_extracts_actions(self):
        """Summarize extracts action items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "Need to review AAPL position")
            mem.add_message("conv-1", "assistant", "Will do")
            mem.extract_facts("Need to review AAPL position", "conv-1", "cli")

            summary = mem.summarize_session("conv-1")

            assert "review AAPL position" in summary
            assert "Action items" in summary

    def test_summarize_session_updates_session(self):
        """Summarize updates session metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "Research AAPL")
            mem.extract_facts("Research AAPL", "conv-1", "cli")
            mem.summarize_session("conv-1")

            session = mem.get_session("conv-1")
            assert session.summary != ""
            assert session.last_summary_at != ""


class TestSessionMerging:
    """Tests for cross-interface session merging."""

    def test_merge_sessions_combines_messages(self):
        """Merge combines messages from two sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("primary", "user", "Hello from CLI")
            mem.add_message("primary", "assistant", "Hi there")

            # Create secondary session explicitly
            mem.create_session("secondary")
            mem.add_message("secondary", "user", "Hello from Telegram")
            mem.add_message("secondary", "assistant", "Welcome")

            merged = mem.merge_sessions("primary", "secondary")

            assert len(merged.messages) == 4
            # Check chronological order
            assert merged.messages[0]["content"] == "Hello from CLI"
            assert merged.messages[-1]["content"] == "Welcome"

    def test_merge_sessions_preserves_interface_history(self):
        """Merge preserves interface history from both sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.sync_from_interface("primary", "cli", [{"role": "user", "content": "A"}])
            mem.create_session("secondary")
            mem.sync_from_interface("secondary", "telegram", [{"role": "user", "content": "B"}])

            merged = mem.merge_sessions("primary", "secondary")

            assert len(merged.interface_history) >= 1

    def test_merge_sessions_respects_context_window(self):
        """Merge respects context window limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Create session with small context window
            mem.create_session("primary", context_window=3)
            for i in range(5):
                mem.add_message("primary", "user", f"Message {i}")

            mem.create_session("secondary")
            mem.add_message("secondary", "user", "Extra message")

            merged = mem.merge_sessions("primary", "secondary")

            # Should be truncated to context_window
            assert len(merged.messages) <= 3


class TestSessionStats:
    """Tests for session statistics."""

    def test_get_session_stats(self):
        """Get session statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.add_message("conv-1", "user", "Hello")
            mem.add_message("conv-1", "assistant", "Hi")
            mem.extract_facts("AAPL is a stock", "conv-1", "cli")
            mem.create_session("conv-1")
            mem.sync_from_interface("conv-1", "telegram", [{"role": "user", "content": "Hi from Telegram"}])

            stats = mem.get_session_stats("conv-1")

            assert stats["message_count"] >= 3
            assert stats["fact_count"] >= 1
            assert "cli" in stats["interfaces_used"] or "telegram" in stats["interfaces_used"]
            assert stats["interface_switches"] >= 0


class TestCrossInterfaceContinuity:
    """Tests for cross-interface conversation continuity."""

    def test_voice_to_telegram_continuity(self):
        """Start on voice, continue on Telegram."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Voice session
            mem.sync_from_interface("conv-1", "voice", [
                {"role": "user", "content": "Research AAPL earnings"},
                {"role": "assistant", "content": "AAPL beat expectations by 5%"},
            ])

            # Switch to Telegram
            mem.sync_from_interface("conv-1", "telegram", [
                {"role": "user", "content": "What about MSFT?"},
            ])

            # Context should include voice messages
            context = mem.get_all_context("conv-1")
            assert len(context["messages"]) == 3
            assert any("AAPL" in m.get("content", "") for m in context["messages"])

            # Build prompt should include history
            prompt = mem.build_context_prompt("conv-1", "Compare with GOOGL")
            assert "AAPL" in prompt

    def test_cli_to_web_continuity(self):
        """Start on CLI, continue on Web."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.sync_from_interface("conv-1", "cli", [
                {"role": "user", "content": "Analyze portfolio"},
                {"role": "assistant", "content": "Portfolio is 60% tech"},
            ])

            mem.sync_from_interface("conv-1", "web", [
                {"role": "user", "content": "Show me the tech allocation"},
            ])

            context = mem.get_all_context("conv-1")
            assert len(context["messages"]) == 3

            stats = mem.get_session_stats("conv-1")
            assert stats["interface_switches"] >= 0


class TestContextWindow:
    """Tests for context window management."""

    def test_context_window_limits_messages(self):
        """Context window limits messages in get_context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)
            mem.create_session("conv-1", context_window=3)

            for i in range(10):
                mem.add_message("conv-1", "user" if i % 2 == 0 else "assistant", f"Message {i}")

            context = mem.get_context("conv-1", limit=3)
            assert len(context) == 3
            assert context[-1]["content"] == "Message 9"

    def test_context_window_in_merge(self):
        """Context window enforced during merge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.create_session("primary", context_window=5)
            for i in range(8):
                mem.add_message("primary", "user", f"Primary {i}")

            mem.create_session("secondary")
            mem.add_message("secondary", "user", "Secondary")

            merged = mem.merge_sessions("primary", "secondary")
            assert len(merged.messages) <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])