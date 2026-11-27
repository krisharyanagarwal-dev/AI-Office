"""Executor tests. The agent call is stubbed; everything else (git, gate, merge) is real,
run against scratch repos in tmp_path."""
import os
import json
import subprocess
from pathlib import Path

import pytest

import core.executor as ex

PATTERNS = json.loads((Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "config" / "office.json").read_text())["autonomy"]["forbidden_path_patterns"]
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *GIT_ID, *args], capture_output=True, text=True, check=True).stdout


def make_repo(root, name="target"):
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "hello.py").write_text("def greet():\n    return 'hi'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def task(repo, tid="t1"):
    return {"id": tid, "title": "Add a docstring", "description": "Document greet().",
            "metadata": {"mode": "act", "repo": str(repo), "agent_id": "software-architect"}}


@pytest.fixture
def scratch(tmp_path):
    repo = make_repo(tmp_path)
    kw = dict(allowlist=[str(repo)], autonomy={"executor_enabled": True, "max_act_tasks_per_day": 6, "forbidden_path_patterns": PATTERNS},
              state_path=tmp_path / "exec_state.json", worktree_root=tmp_path / "wt",
              stop_file=tmp_path / "STOP")
    (tmp_path / "wt").mkdir()
    return repo, kw


def agent_writes(files):
    """Stub for the model call: writes the given {path: text} into the worktree."""
    def _run(task_, worktree, timeout):
        for rel, text in files.items():
            p = Path(worktree) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return "wrote it"
    return _run


# ---------- the diff gate on its own ----------
@pytest.mark.parametrize("path", [".env", "config/.env.local", "com.aryan.thing.plist", "core/executor.py",
                                  "trading/live_orders.py", "exec/order_router.py", "secrets/api_key.txt"])
def test_gate_refuses_protected_paths(path):
    assert ex._path_protected(path, PATTERNS), path


@pytest.mark.parametrize("path", ["hello.py", "core/autopilot.py", "docs/readme.md"])
def test_gate_allows_ordinary_paths(path):
    assert ex._path_protected(path, PATTERNS) is None, path


def test_path_escape_refused():
    reasons = []
    ex._check_path("../outside.py", PATTERNS, reasons)
    ex._check_path("/etc/hosts", PATTERNS, reasons)
    assert len(reasons) == 2


def test_order_code_refused_by_gate(scratch):
    repo, kw = scratch
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "hello.py").write_text("def place_order(x):\n    return x\n")
    reasons = ex.diff_gate(repo, base, PATTERNS)
    assert any("order-placement" in r for r in reasons)
    git(repo, "checkout", "--", "hello.py")


def test_deletion_refused_by_gate(scratch):
    repo, kw = scratch
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "hello.py").unlink()
    git(repo, "add", "-A")
    reasons = ex.diff_gate(repo, base, PATTERNS)
    assert any(r.startswith("deletes") for r in reasons)
    git(repo, "reset", "-q", "--hard")


# ---------- the whole run ----------
def test_clean_change_is_merged_to_main(scratch, monkeypatch):
    repo, kw = scratch
    monkeypatch.setattr(ex, "_run_agent", agent_writes({"hello.py": "def greet():\n    \"\"\"Say hi.\"\"\"\n    return 'hi'\n"}))
    res = ex.run_act_task(task(repo, "ok1"), **kw)
    assert res["changed"] and res["merged"], res
    assert "Say hi" in (repo / "hello.py").read_text()
    assert git(repo, "branch", "--show-current").strip() == "main"
    subjects = git(repo, "log", "--format=%s", "-3")
    assert "office: Add a docstring" in subjects and "office: merge office/ok1" in subjects


def test_rejected_change_is_not_merged_and_patch_is_kept(scratch, monkeypatch):
    repo, kw = scratch
    monkeypatch.setattr(ex, "_run_agent", agent_writes({".env": "API_KEY=x\n"}))
    with pytest.raises(ex.GateRejected):
        ex.run_act_task(task(repo, "bad1"), **kw)
    assert "Say hi" not in (repo / "hello.py").read_text()
    assert not (repo / ".env").exists()
    assert "bad1" in git(repo, "branch", "--list", "office/bad1")
    patch = Path(ex.ROOT) / "logs" / "executor" / "bad1.rejected.patch"
    assert patch.exists() and "API_KEY" in patch.read_text()
    patch.unlink()


def test_compile_failure_blocks_merge(scratch, monkeypatch):
    repo, kw = scratch
    monkeypatch.setattr(ex, "_run_agent", agent_writes({"hello.py": "def broken(:\n"}))
    res = ex.run_act_task(task(repo, "syn1"), **kw)
    assert res["changed"] and not res["merged"]
    assert "compileall failed" in res["detail"]


def test_dirty_repo_keeps_branch_unmerged(scratch, monkeypatch):
    repo, kw = scratch
    (repo / "scratch_note.txt").write_text("someone is working here\n")
    monkeypatch.setattr(ex, "_run_agent", agent_writes({"hello.py": "def greet():\n    return 'yo'\n"}))
    res = ex.run_act_task(task(repo, "dirty1"), **kw)
    assert res["changed"] and not res["merged"]
    assert "not merged" in res["detail"]
    assert "yo" not in (repo / "hello.py").read_text()


def test_stop_file_halts_before_anything_runs(scratch, monkeypatch, tmp_path):
    repo, kw = scratch
    (tmp_path / "STOP").write_text("")
    called = []
    monkeypatch.setattr(ex, "_run_agent", lambda *a, **k: called.append(1))
    with pytest.raises(ex.GateRejected, match="STOP"):
        ex.run_act_task(task(repo, "stop1"), **kw)
    assert not called


def test_daily_cap_is_enforced(scratch, monkeypatch):
    repo, kw = scratch
    kw["autonomy"] = {**kw["autonomy"], "max_act_tasks_per_day": 1}
    monkeypatch.setattr(ex, "_run_agent", agent_writes({"docs/a.md": "a\n"}))
    ex.run_act_task(task(repo, "cap1"), **kw)
    with pytest.raises(ex.GateRejected, match="cap"):
        ex.run_act_task(task(repo, "cap2"), **kw)


def test_non_allowlisted_repo_refused(scratch, tmp_path):
    repo, kw = scratch
    other = make_repo(tmp_path, "elsewhere")
    kw["allowlist"] = [str(repo)]
    with pytest.raises(ex.GateRejected, match="allowlist"):
        ex.run_act_task(task(other, "rej1"), **kw)


def test_executor_is_off_by_default(scratch, monkeypatch):
    repo, kw = scratch
    kw["autonomy"] = {"max_act_tasks_per_day": 6, "forbidden_path_patterns": PATTERNS}
    called = []
    monkeypatch.setattr(ex, "_run_agent", lambda *a, **k: called.append(1))
    with pytest.raises(ex.GateRejected, match="disabled"):
        ex.run_act_task(task(repo, "off1"), **kw)
    assert not called
