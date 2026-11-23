"""End-to-end integration tests for Dost."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def make_mem(tmpdir):
    """Create a memory instance for testing."""
    from dost.memory_pkg.unified import get_unified_memory
    return get_unified_memory()


def test_research_query_end_to_end(tmpdir):
    """Test research query end-to-end through voice -> dispatch -> CLI."""
    mem = make_mem(tmpdir)

    # User asks research question via voice
    mem.sync_from_interface("research-e2e", "voice", [
        {"role": "user", "content": "Analyze AAPL valuation"},
    ])

    # Dispatch to fleet - use direct script path
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "dost_main.py"), "--dispatch", "Analyze AAPL valuation", "--department", "research"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"dispatch failed: {result.stdout}\n{result.stderr}"
    data = json.loads(result.stdout)
    assert data.get("ok") is True
    task_id = data.get("task_id")
    assert task_id is not None

    # Continue conversation on CLI
    mem.sync_from_interface("research-e2e", "cli", [
        {"role": "user", "content": f"Check status of {task_id}"},
    ])

    # Context includes full history
    context = mem.get_all_context("research-e2e")
    assert len(context["messages"]) >= 2

    # Build prompt includes task reference
    prompt = mem.build_context_prompt("research-e2e", "Do you remember the task?")
    assert "Analyze AAPL valuation" in prompt
