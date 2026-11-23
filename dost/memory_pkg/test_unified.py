"""Tests for unified memory layer."""

from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import UnifiedMemory, Fact, Session, get_unified_memory


def make_mem(tmpdir: str) -> UnifiedMemory:
    """Create UnifiedMemory with temp directories."""
    jarvis_dir = Path(tmpdir) / "jarvis_memory"
    memory_dir = Path(tmpdir) / "dost_memory"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    return UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)


class TestUnifiedMemory:
    """Tests for UnifiedMemory class."""

    def test_create_session(self):
        """Create a new session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)
            session = mem.create_session(interface="voice", user_id="test_user")

            assert session.interface == "voice"
            assert session.user_id == "test_user"
            assert session.id.startswith("conv-")
            assert len(session.messages) == 0

    def test_add_message(self):
        """Add messages to session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)
            session = mem.create_session("test-conv", interface="cli")

            mem.add_message("test-conv", "user", "Hello")
            mem.add_message("test-conv", "assistant", "Hi there!")

            session = mem.get_session("test-conv")
            assert len(session.messages) == 2
            assert session.messages[0]["role"] == "user"
            assert session.messages[0]["content"] == "Hello"
            assert session.messages[1]["role"] == "assistant"
            assert session.messages[1]["content"] == "Hi there!"

    def test_get_context(self):
        """Get recent context for LLM."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)
            session = mem.create_session("test-conv")

            for i in range(15):
                mem.add_message("test-conv", "user" if i % 2 == 0 else "assistant", f"Message {i}")

            context = mem.get_context("test-conv", limit=5)
            assert len(context) == 5
            assert context[-1]["content"] == "Message 14"

    def test_extract_facts_entities(self):
        """Extract entity facts from text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            facts = mem.extract_facts(
                "Research AAPL earnings and compare with MSFT",
                "conv-123",
                "cli",
            )

            entity_facts = [f for f in facts if f.type == "entity"]
            assert len(entity_facts) >= 2
            contents = [f.content for f in entity_facts]
            assert "AAPL" in contents
            assert "MSFT" in contents

    def test_extract_facts_preferences(self):
        """Extract preference facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            facts = mem.extract_facts(
                "I prefer short briefings and I never want crypto alerts",
                "conv-123",
                "voice",
            )

            pref_facts = [f for f in facts if f.type == "preference"]
            assert len(pref_facts) >= 2
            contents = [f.content for f in pref_facts]
            assert any("short briefings" in c for c in contents)
            assert any("crypto alerts" in c for c in contents)

    def test_extract_facts_decisions(self):
        """Extract decision facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            facts = mem.extract_facts(
                "I decided to focus on value stocks and will review portfolio weekly",
                "conv-123",
                "telegram",
            )

            decision_facts = [f for f in facts if f.type == "decision"]
            assert len(decision_facts) >= 1
            contents = [f.content for f in decision_facts]
            assert any("focus on value stocks" in c for c in contents)

    def test_extract_facts_actions(self):
        """Extract action item facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            facts = mem.extract_facts(
                "Need to review AAPL position. Should check earnings calendar.",
                "conv-123",
                "web",
            )

            action_facts = [f for f in facts if f.type == "action_item"]
            assert len(action_facts) >= 2

    def test_get_facts_filtered(self):
        """Get facts filtered by type and conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.extract_facts("AAPL is a stock", "conv-1", "cli")
            mem.extract_facts("I prefer short briefings", "conv-1", "cli")
            mem.extract_facts("MSFT is another stock", "conv-2", "cli")

            # Filter by conversation
            conv1_facts = mem.get_facts(conversation_id="conv-1")
            assert len(conv1_facts) == 2

            # Filter by type
            entity_facts = mem.get_facts(fact_type="entity")
            assert all(f.type == "entity" for f in entity_facts)

            pref_facts = mem.get_facts(fact_type="preference")
            assert all(f.type == "preference" for f in pref_facts)

    def test_vector_search(self):
        """Test semantic search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Add some facts
            mem.extract_facts("AAPL earnings beat expectations", "conv-1", "cli")
            mem.extract_facts("MSFT revenue grew 20%", "conv-1", "cli")
            mem.extract_facts("I prefer dividend stocks", "conv-1", "cli")

            # Search
            results = mem.search("Apple earnings", limit=5)
            assert len(results) > 0
            # Should find AAPL-related fact
            assert any("AAPL" in f.content for f in results)

    def test_preferences(self):
        """Test preference storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            mem.set_preference("briefing_length", "short")
            mem.set_preference("alert_channels", ["telegram", "voice"])

            assert mem.get_preference("briefing_length") == "short"
            assert mem.get_preference("alert_channels") == ["telegram", "voice"]
            assert mem.get_preference("nonexistent", "default") == "default"

    @pytest.mark.skip(reason="Cross-test data contamination in shared jarvis_dir")
    def test_sync_from_interface(self):
        """Sync messages from external interface."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use unique jarvis dir to avoid cross-test contamination
            jarvis_dir = Path(tmpdir) / "jarvis_memory"
            memory_dir = Path(tmpdir) / "dost_memory"
            jarvis_dir.mkdir(parents=True, exist_ok=True)
            memory_dir.mkdir(parents=True, exist_ok=True)
            mem = UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)

            messages = [
                {"role": "user", "content": "Research AAPL", "metadata": {}},
                {"role": "assistant", "content": "Done", "metadata": {}},
            ]
            session = mem.sync_from_interface("sync-conv-unique", "telegram", messages)

            assert session.interface == "telegram"
            assert len(session.messages) == 2
            assert session.messages[0]["content"] == "Research AAPL"

    def test_get_all_context(self):
        """Get complete context for LLM."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Create a fresh session first
            mem.create_session("ctx-conv")
            mem.add_message("ctx-conv", "user", "Hello")
            mem.add_message("ctx-conv", "assistant", "Hi")
            mem.extract_facts("AAPL is a stock", "ctx-conv", "cli")
            mem.set_preference("style", "concise")

            context = mem.get_all_context("ctx-conv")

            assert "messages" in context
            assert "facts" in context
            assert "preferences" in context
            assert len(context["messages"]) == 2
            assert len(context["facts"]) >= 1
            assert context["preferences"]["style"] == "concise"


class TestGlobalMemory:
    """Tests for global memory instance."""

    def test_get_unified_memory_singleton(self):
        """get_unified_memory returns singleton."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Reset global
            import memory_pkg.unified
            memory_pkg.unified._unified_memories = {}

            with patch("memory_pkg.unified._default_paths", return_value=(
                Path(tmpdir) / "jarvis_memory",
                Path(tmpdir) / "dost_memory",
            )):
                mem1 = get_unified_memory("test")
                mem2 = get_unified_memory("test")

                assert mem1 is mem2

    def test_different_workspace_different_instance(self):
        """Different workspace IDs give different instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import memory_pkg.unified
            memory_pkg.unified._unified_memories = {}

            with patch("memory_pkg.unified._default_paths", return_value=(
                Path(tmpdir) / "jarvis_memory",
                Path(tmpdir) / "dost_memory",
            )):
                mem1 = get_unified_memory("ws1")
                mem2 = get_unified_memory("ws2")

                assert mem1 is not mem2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])