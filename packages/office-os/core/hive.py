"""
Hive - persistent state layer for Office OS.
Borrows from Munder Difflin's hive: mailbox, memory, task ledger, event log.
All state is JSON files on disk - no database, survives crashes.
Supports user-scoped isolation: every task and message carries a user_id.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

class Hive:
    def __init__(self, root=None):
        # OFFICE_OS_HOME, else ~/office-os. Hardcoding this user's home
        # kept the hive -- mailbox, memory, tasks, logs -- on one machine.
        root = root or (os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))
        self.root = Path(root)
        self.mailbox = self.root / "mailbox"
        self.memory = self.root / "memory"
        self.tasks = self.root / "tasks"
        self.logs = self.root / "logs"
        for d in [self.mailbox, self.memory, self.tasks, self.logs]:
            d.mkdir(parents=True, exist_ok=True)

    # ---------- tasks ----------
    def create_task(self, title, description, agent_id=None, priority="normal",
                    parent_task_id=None, metadata=None, user_id=None):
        task = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "description": description,
            "status": "pending",       # pending | assigned | in_progress | done | failed
            "agent_id": agent_id,
            "priority": priority,       # low | normal | high | critical
            "parent_task_id": parent_task_id,
            "user_id": user_id,         # NEW: user ownership
            "created_at": self._now(),
            "updated_at": self._now(),
            "metadata": metadata or {},
            "result": None,
            "error": None
        }
        self._write_json(self.tasks / f"{task['id']}.json", task)
        self._emit_event("task_created", task_id=task["id"], title=title, agent_id=agent_id, user_id=user_id)
        return task

    def get_task(self, task_id, user_id=None):
        p = self.tasks / f"{task_id}.json"
        if not p.exists():
            return None
        t = self._read_json(p)
        if user_id is not None and t.get("user_id") != user_id:
            return None  # user isolation: cannot see other users' tasks
        return t

    def list_tasks(self, status=None, agent_id=None, user_id=None):
        tasks = []
        for p in self.tasks.glob("*.json"):
            t = self._read_json(p)
            if t is None:
                continue
            if user_id is not None and t.get("user_id") != user_id:
                continue  # user isolation
            if status is not None and t.get("status") != status:
                continue
            if agent_id is not None and t.get("agent_id") != agent_id:
                continue
            tasks.append(t)
        return sorted(tasks, key=lambda x: x.get("created_at", ""))

    def update_task(self, task_id, **fields):
        t = self.get_task(task_id)
        if not t:
            return None
        t.update(fields)
        t["updated_at"] = self._now()
        self._write_json(self.tasks / f"{task_id}.json", t)
        self._emit_event("task_updated", task_id=task_id, fields=fields)
        return t

    # ---------- mailbox ----------
    def send_message(self, from_agent, to_agent, subject, body, task_id=None, user_id=None):
        msg = {
            "id": str(uuid.uuid4())[:8],
            "from": from_agent,
            "to": to_agent,
            "subject": subject,
            "body": body,
            "task_id": task_id,
            "user_id": user_id,
            "created_at": self._now(),
            "read": False
        }
        # Outbox for sender
        self._append_jsonl(self.mailbox / f"outbox_{from_agent}.jsonl", msg)
        # Inbox for recipient
        self._append_jsonl(self.mailbox / f"inbox_{to_agent}.jsonl", msg)
        self._emit_event("message_sent", msg_id=msg["id"], from_agent=from_agent, to_agent=to_agent, user_id=user_id)
        return msg

    def get_inbox(self, agent_id, unread_only=False, user_id=None):
        p = self.mailbox / f"inbox_{agent_id}.jsonl"
        if not p.exists():
            return []
        msgs = self._read_jsonl(p)
        if unread_only:
            msgs = [m for m in msgs if not m.get("read")]
        if user_id is not None:
            msgs = [m for m in msgs if m.get("user_id") == user_id]
        return msgs

    def mark_read(self, agent_id, msg_id):
        p = self.mailbox / f"inbox_{agent_id}.jsonl"
        if not p.exists():
            return
        msgs = self._read_jsonl(p)
        for m in msgs:
            if m["id"] == msg_id:
                m["read"] = True
        self._write_jsonl(p, msgs)

    # ---------- memory ----------
    def remember(self, agent_id, key, value, tags=None, user_id=None):
        entry = {
            "agent_id": agent_id,
            "key": key,
            "value": value,
            "tags": tags or [],
            "user_id": user_id,
            "created_at": self._now()
        }
        self._append_jsonl(self.memory / f"memory_{agent_id}.jsonl", entry)
        return entry

    def recall(self, agent_id, key=None, tag=None, limit=10, user_id=None):
        p = self.memory / f"memory_{agent_id}.jsonl"
        if not p.exists():
            return []
        entries = self._read_jsonl(p)
        if user_id is not None:
            entries = [e for e in entries if e.get("user_id") == user_id]
        if key:
            entries = [e for e in entries if e.get("key") == key]
        if tag:
            entries = [e for e in entries if tag in e.get("tags", [])]
        return entries[-limit:]

    # ---------- event log ----------
    def _emit_event(self, event, **data):
        entry = {
            "event": event,
            "timestamp": self._now(),
            **data
        }
        self._append_jsonl(self.logs / "events.jsonl", entry)

    def get_events(self, event=None, since=None, limit=100, user_id=None):
        p = self.logs / "events.jsonl"
        if not p.exists():
            return []
        events = self._read_jsonl(p)
        if event:
            events = [e for e in events if e.get("event") == event]
        if since:
            events = [e for e in events if e.get("timestamp", "") > since]
        if user_id is not None:
            events = [e for e in events if e.get("user_id") == user_id]
        return events[-limit:]

    # ---------- helpers ----------
    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _write_json(self, path, data):
        """Atomic write: temp file then os.replace() so a crash never leaves a corrupt JSON."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _read_json(self, path):
        """Read JSON with corrupt-file guard: returns None instead of crashing."""
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def _append_jsonl(self, path, data):
        with open(path, "a") as f:
            f.write(json.dumps(data) + "\n")

    def _read_jsonl(self, path):
        if not path.exists():
            return []
        results = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return results

    def _write_jsonl(self, path, data):
        """Atomic write: temp file then os.replace()."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            for d in data:
                f.write(json.dumps(d) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
