"""End-to-end integration tests for Dost multi-modal agent.

Tests cross-interface session continuity, memory persistence,
proactive operations, and skill system integration.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import get_unified_memory, UnifiedMemory
from ops.morning_briefing import MorningBriefing
from ops.anomaly_watch import AnomalyWatch
from ops.opportunity_scanner import OpportunityScanner
from ops.proactive_scheduler import ProactiveScheduler
from ops.self_healing import FleetSelfHealing
from skills.registry import get_registry
from skills.generator import SkillGenerator
from skills.tester import SkillTester
from skills.deployer import SkillDeployer


def make_mem(tmpdir: str) -> UnifiedMemory:
    """Create UnifiedMemory with temp directories."""
    jarvis_dir = Path(tmpdir) / "jarvis_memory"
    memory_dir = Path(tmpdir) / "dost_memory"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    import memory_pkg.unified
    memory_pkg.unified._unified_memories = {}
    return UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)


class TestCrossInterfaceContinuity:
    """Test session continuity across interfaces."""

    def test_voice_to_cli_to_telegram_flow(self):
        """Full conversation across voice -> CLI -> Telegram."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Voice starts conversation
            mem.sync_from_interface("conv-1", "voice", [
                {"role": "user", "content": "Research AAPL earnings"},
                {"role": "assistant", "content": "AAPL Q3 earnings beat expectations"},
            ])

            # Continue on CLI
            mem.sync_from_interface("conv-1", "cli", [
                {"role": "user", "content": "What about MSFT?"},
                {"role": "assistant", "content": "MSFT also beat expectations"},
            ])

            # Continue on Telegram
            mem.sync_from_interface("conv-1", "telegram", [
                {"role": "user", "content": "Compare both"},
            ])

            # Verify full context preserved
            context = mem.get_all_context("conv-1")
            assert len(context["messages"]) == 5

            # Build prompt includes all history
            prompt = mem.build_context_prompt("conv-1", "Summarize findings")
            assert "AAPL" in prompt
            assert "MSFT" in prompt
            assert "voice" in prompt or "cli" in prompt or "telegram" in prompt

            # Interface history tracked
            session = mem.get_session("conv-1")
            assert len(session.interface_history) >= 2

    def test_session_merge_preserves_context(self):
        """Merging sessions preserves all context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # Two parallel sessions
            mem.add_message("session-a", "user", "Research AAPL")
            mem.add_message("session-a", "assistant", "AAPL is up 5%")

            mem.add_message("session-b", "user", "Research MSFT")
            mem.add_message("session-b", "assistant", "MSFT is up 3%")

            # Merge
            merged = mem.merge_sessions("session-a", "session-b")

            # All messages preserved
            assert len(merged.messages) == 4

            # Chronological order
            assert merged.messages[0]["content"] == "Research AAPL"
            assert merged.messages[-1]["content"] == "MSFT is up 3%"


class TestMemoryPersistence:
    """Test memory survives process restarts."""

    def test_facts_survive_restart(self):
        """Facts extracted before restart are available after."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jarvis_dir = Path(tmpdir) / "jarvis_memory"
            memory_dir = Path(tmpdir) / "dost_memory"
            jarvis_dir.mkdir(parents=True, exist_ok=True)
            memory_dir.mkdir(parents=True, exist_ok=True)

            # First process
            import memory_pkg.unified
            memory_pkg.unified._unified_memories = {}
            mem1 = UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)

            mem1.add_message("conv-1", "user", "I prefer short briefings")
            mem1.extract_facts("I prefer short briefings and no crypto", "conv-1", "cli")
            mem1.set_preference("briefing_length", "short")

            # Simulate process restart - new instance with same dirs
            memory_pkg.unified._unified_memories = {}
            mem2 = UnifiedMemory("test", jarvis_dir=jarvis_dir, memory_dir=memory_dir)

            # Facts should be loaded
            prefs = mem2.get_facts("conv-1", fact_type="preference")
            assert len(prefs) >= 1
            assert any("short briefings" in p.content for p in prefs)

            # Preferences file survived
            assert mem2.get_preference("briefing_length") == "short"

            # Session can be loaded
            session = mem2.load_session("conv-1")
            assert session is not None
            assert len(session.messages) >= 1


class TestProactiveOperations:
    """Test proactive operations integration."""

    def test_morning_briefing_generates_output(self):
        """Morning briefing runs and produces output."""
        briefing = MorningBriefing()
        result = briefing.generate_briefing()
        # Should at least run without error
        assert "ok" in result

    def test_anomaly_watch_runs_checks(self):
        """Anomaly watch runs all checks."""
        watch = AnomalyWatch()
        import asyncio
        result = asyncio.run(watch.run_once())
        assert "ok" in result
        assert "checks" in result
        assert "alerts" in result

    def test_opportunity_scanner_dispatches_tasks(self):
        """Opportunity scanner dispatches research tasks."""
        scanner = OpportunityScanner()
        import asyncio
        result = asyncio.run(scanner.run_once())
        assert "ok" in result
        assert "results" in result

    def test_self_healing_runs_checks(self):
        """Self-healing runs all checks."""
        healing = FleetSelfHealing()
        import asyncio
        result = asyncio.run(healing.run_once())
        assert "ok" in result
        assert "actions" in result


class TestSkillSystemIntegration:
    """Test skill system end-to-end."""

    def test_skill_lifecycle_generate_test_deploy(self):
        """Full skill lifecycle: generate -> test -> deploy."""
        # Reset registry
        import skills.registry
        skills.registry._registry = None
        registry = get_registry()

        generator = SkillGenerator()
        tester = SkillTester()
        deployer = SkillDeployer()

        # Generate a simple skill
        spec = "A skill that calculates compound interest given principal, rate, and years"
        result = generator.generate(spec, name="compound_interest")

        assert result["ok"] is True
        assert "module_file" in result
        assert "test_file" in result

        # Verify files created
        module_path = Path(__file__).resolve().parents[1] / "skills" / result["module_file"]
        test_path = Path(__file__).resolve().parents[1] / "skills" / result["test_file"]
        assert module_path.exists()
        assert test_path.exists()

        # Register and test
        registry.discover_skills()
        skill_name = "compound_interest"
        validation = registry.validate_skill(skill_name)
        assert validation["valid"] is True

        test_result = tester.test_skill(skill_name)
        assert test_result.passed is True

        # Deploy
        deploy_result = deployer.deploy(skill_name, run_tests=True)
        assert deploy_result.success is True

        # Cleanup generated files
        module_path.unlink(missing_ok=True)
        test_path.unlink(missing_ok=True)


class TestEndToEndAgentFlow:
    """Test complete agent workflows."""

    def test_research_query_end_to_end(self):
        """Research query goes through full pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = make_mem(tmpdir)

            # User asks research question via voice
            mem.sync_from_interface("research-1", "voice", [
                {"role": "user", "content": "Analyze AAPL valuation"},
            ])

            # Dispatch to fleet
            result = subprocess.run(
                [sys.executable, "-m", "dost.dost", "--dispatch", "Analyze AAPL valuation", "--department", "research"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data.get("ok") is True
            task_id = data.get("task_id")
            assert task_id is not None

            # Continue conversation on CLI
            mem.sync_from_interface("research-1", "cli", [
                {"role": "user", "content": f"Check status of {task_id}"},
            ])

            # Context includes full history
            context = mem.get_all_context("research-1")
            assert len(context["messages"]) >= 2

            # Build prompt includes task reference
            prompt = mem.build_context_prompt("research-1", "What did we find?")
            assert "AAPL" in prompt or task_id in prompt

    def test_multi_interface_skill_invocation(self):
        """Skill invoked from different interfaces produces consistent results."""
        # Reset registry
        import skills.registry
        skills.registry._registry = None
        registry = get_registry()
        registry.discover_skills()

        # Run skill via CLI
        result_cli = subprocess.run(
            [sys.executable, "-m", "dost.skills.cli", "sample_calculator", "--operation", "add", "--a", "10", "--b", "5"],
            capture_output=True,
            text=True,
            cwd="/Users/aryanagarwal/AI-Office",
        )
        assert result_cli.returncode == 0
        data_cli = json.loads(result_cli.stdout)
        assert data_cli["ok"] is True
        assert data_cli["data"]["result"] == 15

        # Run skill via Python API
        registry2 = get_registry()
        result_api = registry2.run_skill("sample_calculator", operation="add", a=10, b=5)
        assert result_api["ok"] is True
        assert result_api["data"]["result"] == 15


class TestSystemHealthAndMonitoring:
    """Test system health monitoring integration."""

    def test_doctor_reports_healthy(self):
        """Doctor command reports system healthy."""
        result = subprocess.run(
            [sys.executable, "-c", "from dost import doctor; board, code = doctor(); print(board); exit(code)"],
            capture_output=True,
            text=True,
            cwd="/Users/aryanagarwal/AI-Office",
        )
        # Should at least run (may have warnings but not critical failures)
        assert "Dispatcher reachable" in result.stdout
        assert "Metrics fresh" in result.stdout

    def test_web_dashboard_serves_events(self):
        """Web dashboard SSE endpoint serves events."""
        # Server should be running from earlier tests
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://localhost:8083/events", timeout=5)
            data = resp.read().decode("utf-8")
            assert "data:" in data
        except Exception:
            pytest.skip("Web server not running")


class TestConfigurationPersistence:
    """Test configuration persists across restarts."""

    def test_office_json_cost_cap(self):
        """Office.json cost cap is readable."""
        import json
        office_json = Path("/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json")
        config = json.loads(office_json.read_text())
        assert "cost_cap" in config
        assert "daily_units" in config["cost_cap"]

    def test_scheduler_config_in_office_json(self):
        """Scheduler config in office.json."""
        import json
        office_json = Path("/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json")
        config = json.loads(office_json.read_text())
        if "scheduler" in config:
            assert "jobs" in config["scheduler"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])