"""Tests for the AI-Office dost CLI wrapper (AI-Office/dost_main.py).

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

_wrapper_path = Path(__file__).resolve().parent.parent / "dost_main.py"
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


# ---------------------------------------------------------------------------
# dispatch flag
# ---------------------------------------------------------------------------

def test_dispatch_runs_successfully():
    # Mock dispatch_prompt_to_fleet on the module so the CLI can still run
    with mock.patch.object(dost, "dispatch_prompt_to_fleet", return_value={"ok": True, "task_id": "abc"}):
        code, out = _run(["--dispatch", "Analyze AAPL valuation"])
    assert code == 0
