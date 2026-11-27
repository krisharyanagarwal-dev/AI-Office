"""Regression tests for bugs found in the uncommitted-changes audit.

1. self_healing.fetch_task_status must resolve the repo-root hive tasks dir.
2. dost_main._orchestrate_plan must skip non-object LLM steps instead of crashing.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from dost import dost_main
from ops import self_healing

REPO_ROOT = Path(self_healing.__file__).resolve().parents[2]
HIVE_TASKS = REPO_ROOT / "packages" / "office-os" / "tasks"


def test_fetch_task_status_reads_repo_root_hive_dir():
    task_id = f"audit-test-{uuid.uuid4().hex[:8]}"
    task_file = HIVE_TASKS / f"{task_id}.json"
    payload = {"id": task_id, "status": "done"}
    HIVE_TASKS.mkdir(parents=True, exist_ok=True)
    task_file.write_text(json.dumps(payload))
    try:
        healer = self_healing.FleetSelfHealing.__new__(self_healing.FleetSelfHealing)
        assert healer.fetch_task_status(task_id) == payload
    finally:
        task_file.unlink(missing_ok=True)


def test_fetch_task_status_missing_returns_empty():
    healer = self_healing.FleetSelfHealing.__new__(self_healing.FleetSelfHealing)
    assert healer.fetch_task_status("no-such-task-xyz") == {}


def _plan_with_llm_text(monkeypatch, text):
    monkeypatch.setattr(dost_main, "build_context", lambda: "CTX")
    monkeypatch.setattr(dost_main, "_chat", lambda *_args, **_kwargs: {"text": text, "provider": "x"})
    return dost_main._orchestrate_plan("goal", "CTX")


def test_orchestrate_plan_skips_non_object_steps(monkeypatch):
    text = '["stray string", 42, {"tool": "web_search", "prompt": "NSE news"}]'
    steps = _plan_with_llm_text(monkeypatch, text)
    assert steps == [{"tool": "web_search", "prompt": "NSE news"}]


def test_orchestrate_plan_all_invalid_falls_back_to_fleet(monkeypatch):
    steps = _plan_with_llm_text(monkeypatch, '["a", 1, null]')
    assert steps == [{"tool": "fleet", "prompt": "goal"}]


def test_run_system_audit_uses_office_core_collectors(monkeypatch):
    """run_system_audit used to raise NameError (OFFICE_CORE undefined)."""
    import sys
    import types

    stub = types.ModuleType("sources")
    stub.collect_all = lambda: [{"name": "x", "ok": True}]
    monkeypatch.setitem(sys.modules, "sources", stub)
    assert dost_main.OFFICE_CORE == dost_main.OFFICE_OS / "core"
    assert dost_main.run_system_audit() == [{"name": "x", "ok": True}]


def test_select_available_pool_binds_names_with_zero_attempts():
    class Orch:
        def decide_model(self, agent_info, task_type="exec"):
            return ("m", "poolA", False)

    model, pool, is_cloud = dost_main._select_available_pool(Orch(), {}, {}, max_attempts=0)
    assert (model, pool, is_cloud) == ("m", "poolA", False)


def test_select_available_pool_prefers_warm_pool():
    class Orch:
        def __init__(self):
            self.seq = [("m1", "cold", True), ("m2", "warm", False)]

        def decide_model(self, agent_info, task_type="exec"):
            return self.seq.pop(0)

    model, pool, is_cloud = dost_main._select_available_pool(Orch(), {}, {"cold": 30}, max_attempts=3)
    assert (model, pool, is_cloud) == ("m2", "warm", False)
