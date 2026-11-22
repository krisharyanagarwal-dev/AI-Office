"""
Executor - the office's hands. Runs 'act' tasks inside a throwaway git worktree
and keeps the result only if deterministic checks pass.

Flow for a task with metadata {"mode": "act", "repo": "<abs path>", "agent_id": "..."}:
  1. Refuse if the STOP file exists, the daily act cap is spent, or the repo is not allowlisted.
  2. Create branch office/<task-id> in a fresh worktree of that repo.
  3. Run `opencode run --agent <agent> --auto` with the worktree as its working directory.
  4. Diff gate (decides, not the model): no deletions, no protected paths, no
     path escapes, no order-placement or live-enable code added.
  5. Commit on the branch. Merge into the repo's main ONLY if the repo is on main,
     its tree is clean, compileall passes, and its tests (if any) pass.
  6. Never push. A failed gate leaves the branch for review and removes the worktree.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os")))
CONFIG_PATH = ROOT / "config" / "office.json"
STATE_PATH = ROOT / "config" / "executor_state.json"
WORKTREE_ROOT = ROOT / "worktrees"
STOP_FILE = ROOT / "STOP"
# A pinned nvm path exists on one machine only; prefer whatever `claude` is on
# PATH and fall back to this user's nvm install.
CLAUDE_FALLBACK = shutil.which("claude") or str(
    Path.home() / ".nvm" / "versions" / "node" / "v22.22.3" / "bin" / "claude"
)
# opencode --auto was tried first and wrote outside its worktree (canary, 2026-11-12); see
# logs/executor/canary-findings.txt. The executor now runs the Claude CLI under sandbox-exec.
AGENT_CALL_TIMEOUT_SEC = 900

# Added lines matching these are rejected outright: the office must never add
# order placement, or switch live trading on.
ORDER_LINE = re.compile(r"(place_order|create_order|submit_order|send_order|live_orders_allowed\s*[:=]\s*true)", re.I)


class GateRejected(Exception):
    """A deterministic check refused the change. The message is the reason."""


def load_autonomy_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text())["autonomy"]


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def check_repo(repo, allowlist):
    """Return the real path of an allowlisted git repo, or refuse."""
    real = os.path.realpath(str(repo))
    allowed = {os.path.realpath(p) for p in allowlist}
    if real not in allowed:
        raise GateRejected(f"repo is not on the allowlist: {repo}")
    if not (Path(real) / ".git").exists():
        raise GateRejected(f"not a git repository: {repo}")
    return real


def _path_protected(path, patterns):
    """Fail closed: a pattern matches the basename, the full path, or (if it has no
    wildcard) appears anywhere in the path. Over-blocking is acceptable here."""
    low = path.lower()
    name = Path(path).name.lower()
    for pat in patterns:
        p = pat.lower()
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(low, p):
            return pat
        if "*" not in p and p in low:
            return pat
    return None


def diff_gate(worktree, base, patterns):
    """Deterministic checks on what the agent changed. Returns a list of reasons; empty means pass."""
    reasons = []
    for line in _git(worktree, "diff", "--name-status", base).splitlines():
        status, _, path = line.partition("\t")
        if status.startswith("D"):
            reasons.append(f"deletes {path}")
        _check_path(path, patterns, reasons)
    for path in _git(worktree, "ls-files", "--others", "--exclude-standard").splitlines():
        _check_path(path, patterns, reasons)
    for line in _git(worktree, "diff", base).splitlines():
        if line.startswith("+") and not line.startswith("+++") and ORDER_LINE.search(line):
            reasons.append("adds order-placement or live-enable code")
            break
    return reasons


def _check_path(path, patterns, reasons):
    if not path or path.startswith("/") or ".." in Path(path).parts:
        reasons.append(f"path escapes the worktree: {path!r}")
        return
    hit = _path_protected(path, patterns)
    if hit:
        reasons.append(f"touches protected path {path} (matches {hit!r})")


def _budget(state_path, cap):
    """Return (allowed, state). The day rolls over at local midnight."""
    today = datetime.now().strftime("%Y-%m-%d")
    st = {"day": today, "act_count": 0}
    try:
        loaded = json.loads(Path(state_path).read_text())
        if loaded.get("day") == today:
            st = loaded
    except (OSError, json.JSONDecodeError):
        pass
    return st["act_count"] < cap, st


def _spend(state_path, st):
    st["act_count"] += 1
    tmp = Path(state_path).with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(tmp, state_path)


def _act_prompt(task):
    return (
        f"Task: {task['title']}\n\n{task.get('description', '')}\n\n"
        "Rules you must follow:\n"
        "- Work only inside the current directory, which is a git worktree of the target repo.\n"
        "- Make the smallest change that completes the task. Do not refactor unrelated code.\n"
        "- Never touch .env files, keys, secrets, launchd plists, or any trading order code.\n"
        "- Do not commit, push, or delete files. The office commits your changes after review.\n"
        "- Finish with a short plain-text summary of what you changed and why."
    )


def _confine_profile(worktree):
    """macOS sandbox profile: file writes allowed only inside the worktree (plus the
    temp dir and the agent's own state dirs). Tool-name restrictions do not contain
    absolute-path writes; the OS-level profile does (verified in the canary)."""
    w = os.path.realpath(str(worktree))
    home = str(Path.home())
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny file-write*)\n"
        f'(allow file-write* (subpath "{w}"))\n'
        '(allow file-write* (subpath "/private/var/folders"))\n'
        '(allow file-write* (literal "/dev/null"))\n'
        f'(allow file-write* (regex "^{home}/\\\\.claude"))\n'
        f'(allow file-write* (regex "^{home}/\\\\.config"))\n'
    )


def _run_agent(task, worktree, timeout):
    """Run the agent under the write-confinement profile. The profile file is written
    beside the worktrees, outside the area it confines."""
    meta = task.get("metadata") or {}
    model = meta.get("model") or "claude-haiku-5-5"
    claude = shutil.which("claude") or CLAUDE_FALLBACK
    profile = Path(WORKTREE_ROOT) / f"{task['id']}.sb"
    profile.write_text(_confine_profile(worktree))
    cmd = ["sandbox-exec", "-f", str(profile), claude, "-p", _act_prompt(task),
           "--model", model, "--allowedTools", "Read", "Edit", "Write", "Glob", "Grep",
           "--permission-mode", "acceptEdits", "--max-budget-usd", "1.00", "--output-format", "text"]
    r = subprocess.run(cmd, cwd=str(worktree), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"agent exited {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip()[-2000:]


def _merge_gate(worktree):
    """Compile and test the branch before it is allowed onto main. Returns (ok, detail)."""
    py_files = [f for f in _git(worktree, "ls-files", "*.py").splitlines() if f]
    if py_files:
        r = subprocess.run(["python3", "-m", "compileall", "-q", "."], cwd=str(worktree),
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, f"compileall failed: {(r.stdout + r.stderr).strip()[-300:]}"
    if (Path(worktree) / "tests").is_dir():
        r = subprocess.run(["python3", "-m", "pytest", "-q", "tests"], cwd=str(worktree),
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False, f"tests failed: {r.stdout.strip()[-300:]}"
    return True, "compile and tests passed"


def _cleanup_worktree(repo, wt):
    try:
        _git(repo, "worktree", "remove", "--force", str(wt), check=False)
    except Exception:
        pass


def run_act_task(task, *, allowlist=None, autonomy=None, state_path=STATE_PATH,
                 worktree_root=WORKTREE_ROOT, stop_file=STOP_FILE, agent_timeout=AGENT_CALL_TIMEOUT_SEC):
    """Execute one act-task. Returns a result dict on success; raises GateRejected or
    RuntimeError otherwise. Parameters beyond `task` exist so tests can use scratch repos."""
    cfg = autonomy or load_autonomy_config()
    allow = allowlist if allowlist is not None else cfg["repo_allowlist"]
    if not cfg.get("executor_enabled", False):
        raise GateRejected("executor disabled: act-tasks stay off until the sandbox canary is accepted")
    if Path(stop_file).exists():
        raise GateRejected("STOP file present: act-tasks are halted")
    allowed, st = _budget(state_path, int(cfg["max_act_tasks_per_day"]))
    if not allowed:
        raise GateRejected("daily act-task cap reached")

    meta = task.get("metadata") or {}
    if not meta.get("repo"):
        raise GateRejected("act-task has no target repo")
    repo = check_repo(meta["repo"], allow)
    task_id = task["id"]
    branch = f"office/{task_id}"
    wt = Path(worktree_root) / f"act-{task_id}"
    base = _git(repo, "rev-parse", "HEAD").strip()

    _git(repo, "worktree", "add", "-b", branch, str(wt), "HEAD")
    _spend(state_path, st)  # the attempt counts even if it is rejected
    try:
        agent_out = _run_agent(task, wt, agent_timeout)
        reasons = diff_gate(wt, base, cfg["forbidden_path_patterns"])
        if reasons:
            raise GateRejected("; ".join(reasons))
        if not _git(wt, "status", "--porcelain").strip():
            _cleanup_worktree(repo, wt)
            return {"changed": False, "branch": branch, "merged": False, "summary": "no changes made"}

        _git(wt, "add", "-A")
        _git(wt, "-c", "user.name=office", "-c", "user.email=office@localhost",
             "commit", "-q", "-m", f"office: {task['title'][:60]}\n\nTask {task_id}")

        merged, detail = False, "merge skipped"
        on_main = _git(repo, "branch", "--show-current").strip() == "main"
        clean = not _git(repo, "status", "--porcelain").strip()
        if not (on_main and clean):
            detail = "not merged: repo is not on main with a clean tree (branch kept for review)"
        else:
            ok, detail = _merge_gate(wt)
            if ok:
                _git(repo, "-c", "user.name=office", "-c", "user.email=office@localhost",
                     "merge", "--no-ff", "-q", branch, "-m", f"office: merge {branch}")
                merged = True
        _cleanup_worktree(repo, wt)
        return {"changed": True, "branch": branch, "merged": merged, "detail": detail,
                "summary": agent_out[:800]}
    except Exception:
        # Keep the rejected diff as evidence before the worktree (and its uncommitted work) is removed.
        try:
            _git(wt, "add", "-A", check=False)
            patch = _git(wt, "diff", "--cached", base, check=False)
            if patch.strip():
                out = ROOT / "logs" / "executor"
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{task_id}.rejected.patch").write_text(patch)
        except Exception:
            pass
        _cleanup_worktree(repo, wt)  # the branch stays so a rejected change can be inspected
        raise
