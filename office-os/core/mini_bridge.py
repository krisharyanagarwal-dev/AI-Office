"""
Mini bridge - hands work from office-os to the Mac mini office and closes it on return.

Contract (matches the mini's autonomous_office.py, Phase 4):
  * A hive task with metadata {"target": "mini", "mini_type": "<allowed type>"} is delivered
    as one JSON file into the mini's inbox, written atomically over ssh.
  * The mini answers by writing outbox/<task-id>.json with status completed|failed|rejected.
  * The task stays "pending" the whole time, so the orchestrator never dispatches it locally.
    It is marked "done" or "failed" only from a verdict whose id matches a task we delivered.

Rules:
  * Mini unreachable  -> nothing changes; the task stays queued and is retried later. Never failed.
  * STOP file present -> no deliveries and no verdict reads.
  * Task ids are validated before they reach a remote shell command.
  * Task types are an explicit allowlist. Anything else is refused and marked failed locally.
  * Verdict files for unknown ids are logged and ignored.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/aryanagarwal/office-os")
STOP_FILE = ROOT / "STOP"
MINI = "a@macmini"
INBOX = "~/ai-office/data/office-inbox"
OUTBOX = "~/ai-office/data/office-outbox"
SSH_TIMEOUT = 20
MAX_DELIVERIES_PER_CYCLE = 5
# The mini's own worker types that accept inbox work. Keep this list short and explicit.
ALLOWED_TYPES = {"summary", "analysis", "research", "report", "doc"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _now():
    return datetime.now(timezone.utc).isoformat()


class SshRunner:
    """Runs one remote command over the existing alias. Returns (rc, stdout, stderr).
    rc is None when ssh itself could not run or timed out."""

    def run(self, remote_cmd, stdin_text=None):
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_TIMEOUT // 2}", MINI, remote_cmd],
                input=stdin_text, capture_output=True, text=True, timeout=SSH_TIMEOUT,
            )
            return r.returncode, r.stdout, r.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, "", f"{type(e).__name__}"


class MiniBridge:
    def __init__(self, hive, runner=None, stop_file=STOP_FILE):
        self.hive = hive
        self.runner = runner or SshRunner()
        self.stop_file = Path(stop_file)

    # ---------- selection ----------
    def _is_mini_task(self, task):
        return (task.get("metadata") or {}).get("target") == "mini"

    def _queued(self):
        return [t for t in self.hive.list_tasks(status="pending")
                if self._is_mini_task(t) and not (t.get("metadata") or {}).get("mini_delivered_at")]

    def _awaiting(self):
        return [t for t in self.hive.list_tasks(status="pending")
                if self._is_mini_task(t) and (t.get("metadata") or {}).get("mini_delivered_at")]

    def _note(self, task, **meta):
        md = dict(task.get("metadata") or {})
        md.update(meta)
        self.hive.update_task(task["id"], metadata=md)

    # ---------- delivery ----------
    def _payload(self, task):
        md = task.get("metadata") or {}
        return {
            "id": task["id"],
            "type": md.get("mini_type"),
            "prompt": f"{task['title']}\n\n{task.get('description', '')}".strip(),
            "from": "office-os",
            "sent_at": _now(),
        }

    def deliver(self, task):
        md = task.get("metadata") or {}
        mtype = md.get("mini_type")
        if mtype not in ALLOWED_TYPES:
            self.hive.update_task(task["id"], status="failed",
                                  error=f"mini task type not allowed: {mtype!r}")
            return "refused"
        if not ID_RE.match(task["id"]):
            self.hive.update_task(task["id"], status="failed", error="task id not safe to send")
            return "refused"
        body = json.dumps(self._payload(task), indent=2)
        name = f"{task['id']}.json"
        cmd = (f"cat > {INBOX}/.{name}.tmp && mv {INBOX}/.{name}.tmp {INBOX}/{name}")
        rc, _, err = self.runner.run(cmd, stdin_text=body)
        if rc != 0:
            return f"queued ({'unreachable' if rc is None else f'ssh exit {rc}'}: {err.strip()[:80]})"
        self._note(task, mini_delivered_at=_now(), mini_state="delivered")
        return "delivered"

    # ---------- verdicts ----------
    def _read_verdict(self, task_id):
        if not ID_RE.match(task_id):
            return None, "unsafe id"
        rc, out, _ = self.runner.run(f"cat {OUTBOX}/{task_id}.json 2>/dev/null")
        if rc is None:
            return None, "unreachable"
        if rc != 0 or not out.strip():
            return None, "no verdict yet"
        try:
            return json.loads(out), None
        except json.JSONDecodeError:
            return None, "verdict unreadable"

    def collect(self, task):
        verdict, why = self._read_verdict(task["id"])
        if verdict is None:
            return why
        status = verdict.get("status")
        if status == "completed":
            self.hive.update_task(task["id"], status="done", result={
                "source": "mini", "preview": verdict.get("preview", ""),
                "jev_judgment": verdict.get("jev_judgment"), "stored": verdict.get("stored"),
                "finished_at": verdict.get("finished_at"),
            })
            return "done"
        reason = str(verdict.get("reason") or status or "no reason given")[:300]
        self.hive.update_task(task["id"], status="failed", error=f"mini {status}: {reason}")
        return "failed"

    # ---------- one cycle ----------
    def cycle(self):
        """Deliver queued mini tasks and collect verdicts. Returns a short report."""
        if self.stop_file.exists():
            return {"skipped": "STOP file present"}
        report = {"delivered": [], "collected": [], "queued": 0}
        for task in self._queued()[:MAX_DELIVERIES_PER_CYCLE]:
            result = self.deliver(task)
            if result == "delivered":
                report["delivered"].append(task["id"])
            elif result.startswith("queued"):
                report["queued"] += 1
                report["last_queue_reason"] = result
                break  # mini is unreachable: stop trying for this cycle
        for task in self._awaiting():
            result = self.collect(task)
            if result in ("done", "failed"):
                report["collected"].append((task["id"], result))
        return report
