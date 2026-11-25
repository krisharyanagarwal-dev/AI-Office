"""Tests for fleet dispatch correctness (dispatch_prompt_to_fleet)."""

from __future__ import annotations

import json

from dost import dost_main


def test_dispatch_dry_run_writes_nothing(tmp_path, monkeypatch):
    """dry_run returns a preview without touching HIVE_DIR."""
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    result = dost_main.dispatch_prompt_to_fleet(
        "research RELIANCE.NS opening range",
        agent_id="market-analyst",
        priority="high",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["agent_id"] == "market-analyst"
    assert result["priority"] == "high"
    assert result["task_id"].startswith("jev-")
    assert "DRY RUN" in result["message"]
    assert result["task_preview"]["description"] == "research RELIANCE.NS opening range"
    assert result["task_preview"]["agent_id"] == "market-analyst"
    assert not hive.exists() or not any(hive.glob("*.json"))


def test_dispatch_writes_task_file_with_all_fields(tmp_path, monkeypatch):
    """A real dispatch writes one task file to HIVE_DIR with expected fields."""
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    result = dost_main.dispatch_prompt_to_fleet(
        "Check the NSE opening range for RELIANCE.NS",
        agent_id="market-analyst",
        priority="high",
    )

    assert result["ok"] is True
    assert result.get("dry_run") is None
    assert result["agent_id"] == "market-analyst"
    assert result["priority"] == "high"
    task_id = result["task_id"]
    assert task_id.startswith("jev-")

    task_path = hive / f"{task_id}.json"
    assert task_path.exists()

    task = json.loads(task_path.read_text())
    assert task["id"] == task_id
    assert task["title"] == "Dost prompt: Check the NSE opening range for RELIANCE.NS"
    assert task["description"] == "Check the NSE opening range for RELIANCE.NS"
    assert task["status"] == "pending"
    assert task["agent_id"] == "market-analyst"
    assert task["priority"] == "high"
    assert task["user_id"] == "dost"
    assert task["result"] is None
    assert task["error"] is None
    assert task["metadata"]["tier"] == "pro"
    assert task["metadata"]["source"] == "dost"
    assert task["metadata"]["qwen_task_id"].startswith(f"jev-exec-dost-{task_id[:8]}")
    assert task["created_at"].endswith("Z")
    assert task["updated_at"].endswith("Z")


def test_dispatch_defaults_agent_id_to_strategy_advisor(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    result = dost_main.dispatch_prompt_to_fleet("ping the fleet")

    assert result["agent_id"] == "strategy-advisor"
    task = json.loads((hive / f"{result['task_id']}.json").read_text())
    assert task["agent_id"] == "strategy-advisor"


def test_dispatch_priority_forwarded(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    for priority in ("low", "normal", "high"):
        result = dost_main.dispatch_prompt_to_fleet("ping", priority=priority)
        assert result["priority"] == priority
        task = json.loads((hive / f"{result['task_id']}.json").read_text())
        assert task["priority"] == priority


def test_dispatch_parent_task_id_threads_metadata(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)
    parent = "jev-parent1234"

    result = dost_main.dispatch_prompt_to_fleet("follow up on that", parent_task_id=parent)

    assert result["ok"] is True
    task = json.loads((hive / f"{result['task_id']}.json").read_text())
    assert task["metadata"]["parent_task_id"] == parent
    assert task["title"].startswith(f"Follow-up to {parent[:8]}:")


def test_dispatch_chain_stored_in_metadata(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)
    chain = {
        "prompt": "what changed since then?",
        "agent_id": "strategy-advisor",
        "priority": "low",
    }

    result = dost_main.dispatch_prompt_to_fleet("initial read", chain=chain)

    assert result["ok"] is True
    task = json.loads((hive / f"{result['task_id']}.json").read_text())
    assert task["metadata"]["chain"] == chain
    assert task["title"].startswith("Chain parent:")


def test_dispatch_workspace_id_recorded(tmp_path, monkeypatch):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    result = dost_main.dispatch_prompt_to_fleet("do it", workspace_id="ws-alpha")

    assert result["ok"] is True
    task = json.loads((hive / f"{result['task_id']}.json").read_text())
    assert task["metadata"]["workspace_id"] == "ws-alpha"


def test_dispatch_debug_prints_task_info(tmp_path, monkeypatch, capsys):
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    dost_main.dispatch_prompt_to_fleet("ping", debug=True)

    out = capsys.readouterr().out
    assert "[debug] dispatch_prompt_to_fleet" in out
    assert "dry_run=False" in out
    assert "parent=none" in out


def test_dispatch_write_failure_returns_ok_false(monkeypatch):
    """An unwritable HIVE_DIR degrades to {"ok": False, "error": ...}."""

    class FailingPath:
        def write_text(self, *args, **kwargs):
            raise OSError("disk full")

    class FailingHive:
        def mkdir(self, *args, **kwargs):
            raise OSError("disk full")

        def __truediv__(self, name):
            return FailingPath()

    monkeypatch.setattr(dost_main, "HIVE_DIR", FailingHive())

    result = dost_main.dispatch_prompt_to_fleet("ping")

    assert result["ok"] is False
    assert "disk full" in result["error"]


def test_dispatch_rejects_overlong_prompt(tmp_path, monkeypatch):
    """Prompts over the length cap are rejected with ok=False and no task file written."""
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    overlong = "x" * (dost_main.MAX_DISPATCH_PROMPT_LEN + 1)

    result = dost_main.dispatch_prompt_to_fleet(overlong)

    assert result["ok"] is False
    assert "too long" in result["error"].lower()
    assert str(dost_main.MAX_DISPATCH_PROMPT_LEN) in result["error"]
    assert not hive.exists() or not any(hive.glob("*.json"))


def test_dispatch_accepts_prompt_at_exact_limit(tmp_path, monkeypatch):
    """A prompt exactly at the length cap is still accepted."""
    hive = tmp_path / "hive"
    monkeypatch.setattr(dost_main, "HIVE_DIR", hive)

    at_limit = "x" * dost_main.MAX_DISPATCH_PROMPT_LEN

    result = dost_main.dispatch_prompt_to_fleet(at_limit)

    assert result["ok"] is True
    assert (hive / f"{result['task_id']}.json").exists()
