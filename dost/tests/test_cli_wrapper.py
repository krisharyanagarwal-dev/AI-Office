"""Tests for the AI-Office dost CLI wrapper (AI-Office/dost.py).

Covers the exit-code contract, flag wiring, dry-run side-effect contract,
and workspace subcommand routing for the vendored copy of the CLI.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from unittest import mock

import pytest

_wrapper_path = Path(__file__).resolve().parent.parent.parent / "dost.py"
_spec = importlib.util.spec_from_file_location("dost_aio_wrapper", _wrapper_path)
dost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dost)


def _run(argv):
    """Run dost.main() with the given argv.

    Returns (exit_code, captured_stdout). A normal return (no sys.exit)
    is treated as exit code 0.
    """
    old_argv = sys.argv
    old_exit = sys.exit
    buf = io.StringIO()
    real_stdout = sys.stdout
    code = [None]

    def fake_exit(c=0):
        code[0] = c if c is not None else 0
        raise SystemExit(code[0])

    sys.argv = ["dost.py"] + argv
    sys.stdout = buf
    sys.exit = fake_exit
    try:
        dost.main()
    except SystemExit:
        pass
    finally:
        sys.stdout = real_stdout
        sys.argv = old_argv
        sys.exit = old_exit
    return code[0] if code[0] is not None else 0, buf.getvalue()


# ---------------------------------------------------------------------------
# workspace subcommand routing
# ---------------------------------------------------------------------------

def test_workspace_list_exits_zero():
    code, _ = _run(["workspace", "list"])
    assert code == 0


def test_workspace_create_without_name_exits_one():
    code, out = _run(["workspace", "create"])
    assert code == 1
    assert "Usage" in out


def test_workspace_add_user_without_email_exits_one():
    code, out = _run(["workspace", "add-user", "ws-123"])
    assert code == 1
    assert "Usage" in out


def test_workspace_add_user_unknown_workspace_exits_one_with_clean_error():
    code, out = _run(
        ["workspace", "add-user", "ws-does-not-exist-xyz", "a@b.com", "viewer"]
    )
    assert code == 1
    assert "not found" in out


# ---------------------------------------------------------------------------
# dispatch priority flag
# ---------------------------------------------------------------------------

def test_dispatch_uses_priority_flag():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": True, "task_id": "abc"},
    ) as m:
        code, _ = _run(["--dispatch", "x", "--priority", "high"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "high"


def test_dispatch_defaults_to_normal_priority():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": True, "task_id": "abc"},
    ) as m:
        code, _ = _run(["--dispatch", "x"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "normal"


def test_results_status_is_not_used_as_dispatch_priority():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": True, "task_id": "abc"},
    ) as m:
        code, _ = _run(["--dispatch", "x", "--results-status", "done"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "normal"


def test_batch_uses_priority_flag():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": True, "task_id": "abc"},
    ) as m:
        code, _ = _run(["--batch", "p1,p2", "--priority", "low"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "low"


def test_backtest_threads_priority_flag():
    with mock.patch.object(
        dost, "run_strategy_pipeline", return_value={"ok": True}
    ) as m:
        code, _ = _run(["--backtest", "mean reversion", "--priority", "critical"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "critical"


def test_backtest_defaults_to_normal_priority():
    with mock.patch.object(
        dost, "run_strategy_pipeline", return_value={"ok": True}
    ) as m:
        code, _ = _run(["--backtest", "mean reversion"])
    assert code == 0
    assert m.call_args.kwargs["priority"] == "normal"


def test_backtest_threads_dry_run_flag():
    with mock.patch.object(
        dost, "run_strategy_pipeline", return_value={"status": "dry_run"}
    ) as m:
        code, _ = _run(["--backtest", "mean reversion", "--dry-run"])
    assert code == 0
    assert m.call_args.kwargs.get("dry_run") is True


def test_backtest_exits_one_when_pipeline_reports_error():
    with mock.patch.object(
        dost, "run_strategy_pipeline",
        return_value={"status": "error", "error": "dispatch failed"},
    ):
        code, _ = _run(["--backtest", "mean reversion"])
    assert code == 1


def test_strategy_pipeline_dry_run_writes_no_task_file(tmp_path):
    pipeline = dost._strategy_pipeline_module
    fleet_module = sys.modules["dost.dost"]
    with mock.patch.object(fleet_module, "HIVE_DIR", tmp_path):
        result = pipeline.run_strategy_pipeline("mean reversion", dry_run=True)
    assert result["status"] == "dry_run"
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# flag threading into the inner module
# ---------------------------------------------------------------------------

def test_dispatch_threads_debug_flag():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": True, "task_id": "abc"},
    ) as m:
        code, _ = _run(["--dispatch", "x", "--debug"])
    assert code == 0
    assert m.call_args.kwargs.get("debug") is True


def test_debate_threads_dry_run_flag():
    with mock.patch.object(
        dost._dost_module, "dispatch_debate_to_fleet",
        return_value={"debate_id": "d1", "dry_run": True, "agents": ["a"]},
    ) as m:
        code, _ = _run(["--debate", "q", "--dry-run"])
    assert code == 0
    assert m.call_args.kwargs.get("dry_run") is True


def test_debate_threads_debug_flag():
    with mock.patch.object(
        dost._dost_module, "dispatch_debate_to_fleet",
        return_value={"debate_id": "d1", "agents": ["a"]},
    ) as m:
        code, _ = _run(["--debate", "q", "--debug"])
    assert code == 0
    assert m.call_args.kwargs.get("debug") is True


# ---------------------------------------------------------------------------
# non-zero exit codes on failure paths
# ---------------------------------------------------------------------------

def test_dispatch_exits_one_when_ok_false():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        return_value={"ok": False, "error": "boom"},
    ):
        code, _ = _run(["--dispatch", "x"])
    assert code == 1


def test_batch_exits_one_on_any_failure():
    with mock.patch.object(
        dost._dost_module, "dispatch_prompt_to_fleet",
        side_effect=[
            {"ok": True, "task_id": "a"},
            {"ok": False, "error": "boom"},
        ],
    ):
        code, _ = _run(["--batch", "p1,p2"])
    assert code == 1


# ---------------------------------------------------------------------------
# module-level dry-run and debug contracts
# ---------------------------------------------------------------------------

def test_dispatch_prompt_debug_prints_written_task_file(tmp_path):
    mod = dost._dost_module
    buf = io.StringIO()
    with mock.patch.object(mod, "HIVE_DIR", tmp_path):
        with mock.patch.object(sys, "stdout", buf):
            result = mod.dispatch_prompt_to_fleet("hello", debug=True)
    out = buf.getvalue()
    assert result["ok"] is True
    assert "dispatch_prompt_to_fleet:" in out
    assert "wrote task file" in out
    assert (tmp_path / f"{result['task_id']}.json").exists()


def test_dispatch_prompt_dry_run_writes_nothing_even_with_debug(tmp_path):
    mod = dost._dost_module
    buf = io.StringIO()
    with mock.patch.object(mod, "HIVE_DIR", tmp_path):
        with mock.patch.object(sys, "stdout", buf):
            result = mod.dispatch_prompt_to_fleet("hello", dry_run=True, debug=True)
    assert result["ok"] is True and result["dry_run"] is True
    assert list(tmp_path.iterdir()) == []
    assert "wrote task file" not in buf.getvalue()


def test_dispatch_debate_dry_run_returns_without_writes(tmp_path):
    mod = dost._dost_module
    buf = io.StringIO()
    with mock.patch.object(mod, "HIVE_DIR", tmp_path):
        with mock.patch.object(sys, "stdout", buf):
            result = mod.dispatch_debate_to_fleet("q", dry_run=True)
    assert result["dry_run"] is True
    assert result["task_ids"] == []
    assert result["cost_units"] == 0
    assert list(tmp_path.iterdir()) == []


def test_dispatch_debate_dry_run_debug_lists_agents(tmp_path):
    mod = dost._dost_module
    buf = io.StringIO()
    with mock.patch.object(mod, "HIVE_DIR", tmp_path):
        with mock.patch.object(sys, "stdout", buf):
            result = mod.dispatch_debate_to_fleet("q", dry_run=True, debug=True)
    out = buf.getvalue()
    assert result["dry_run"] is True
    assert "debate dry-run" in out
    assert "strategy-advisor" in out
    assert list(tmp_path.iterdir()) == []
