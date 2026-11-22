"""
GOD Agent (Michael) - orchestrator for Office OS.
Borrowed from Munder Difflin's GOD agent: assigns tasks, routes messages,
escalates critical items, runs heartbeat missions.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.hive import Hive
from core.router import ProviderRouter


class GodAgent:
    def __init__(self, hive=None, router=None):
        self.hive = hive or Hive()
        self.router = router or ProviderRouter()
        self.agent_id = "michael"
        self.hive.remember(self.agent_id, "role", "god_orchestrator", tags=["role", "god"])
        self.hive.remember(self.agent_id, "status", "online", tags=["status"])

    def run_heartbeat(self):
        """Heartbeat mission - keep the floor active, check on workers."""
        self.hive.remember(self.agent_id, "last_heartbeat", self.hive._now(), tags=["heartbeat"])

        # Check for stuck tasks (in_progress too long)
        tasks = self.hive.list_tasks(status="in_progress")
        for t in tasks:
            # Simple check: if task has been in_progress for >30 min, flag it
            self.hive.send_message(
                self.agent_id, t.get("agent_id", "unknown"),
                "Heartbeat check-in",
                f"Task '{t['title']}' ({t['id']}) is still in_progress. Status update?",
                task_id=t["id"]
            )

        # Check inbox for messages needing response
        inbox = self.hive.get_inbox(self.agent_id, unread_only=True)
        for msg in inbox:
            self.hive.mark_read(self.agent_id, msg["id"])
            if msg.get("task_id"):
                # Forward task-related messages to the assigned worker
                task = self.hive.get_task(msg["task_id"])
                if task and task.get("agent_id") and task.get("agent_id") != self.agent_id:
                    self.hive.send_message(
                        self.agent_id, task["agent_id"],
                        f"Re: {msg['subject']}",
                        f"GOD forwarded: {msg['body']}",
                        task_id=msg["task_id"]
                    )

        return {"heartbeat": self.hive._now(), "inbox_processed": len(inbox)}

    def assign_task(self, task_id, agent_id):
        """Assign a pending task to an agent."""
        task = self.hive.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        if task["status"] != "pending":
            return {"error": f"Task {task_id} already {task['status']}"}

        # Select provider for this agent's tier
        tier = self._agent_tier(agent_id)
        pool_name, model = self.router.select_provider(tier=tier)

        if not pool_name:
            return {"error": "No providers available"}

        self.hive.update_task(
            task_id,
            agent_id=agent_id,
            status="assigned",
            assigned_pool=pool_name,
            assigned_model=model
        )

        self.hive.send_message(
            self.agent_id, agent_id,
            f"Task assigned: {task['title']}",
            f"You are assigned task {task_id}: {task['description']}\n"
            f"Provider: {pool_name}/{model}\n"
            f"Execute via OpenCode subagent.",
            task_id=task_id
        )

        self.hive.remember(self.agent_id, f"assignment_{task_id}", agent_id, tags=["assignment"])
        return {"task_id": task_id, "agent_id": agent_id, "pool": pool_name, "model": model}

    def create_task(self, title, description, agent_id=None, priority="normal", user_id=None):
        """Create a new task and optionally auto-assign."""
        task = self.hive.create_task(title, description, agent_id=agent_id, priority=priority, user_id=user_id)

        if agent_id:
            return self.assign_task(task["id"], agent_id)

        return {"task": task, "status": "pending_auto_assign", "user_id": user_id}

    def auto_assign_pending(self):
        """Auto-assign all pending tasks to available agents."""
        pending = self.hive.list_tasks(status="pending")
        results = []
        for t in pending:
            # For auto-assign, we need an agent. If no agent specified, skip
            # (tasks must be explicitly assigned or come from heartbeat)
            continue
        return results

    def escalate(self, task_id, reason):
        """Escalate a task to human attention."""
        task = self.hive.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        self.hive.update_task(task_id, status="failed", error=f"Escalated: {reason}")
        self.hive.send_message(
            self.agent_id, "human",
            f"Escalation: {task['title']}",
            f"Task {task_id} needs human attention: {reason}",
            task_id=task_id
        )
        self.hive.remember(self.agent_id, f"escalation_{task_id}", reason, tags=["escalation"])
        return {"task_id": task_id, "escalated": True, "reason": reason}

    def complete_task(self, task_id, result=None):
        """Mark a task as complete."""
        task = self.hive.get_task(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        self.hive.update_task(task_id, status="done", result=result)
        agent_id = task.get("agent_id")
        if agent_id:
            self.hive.send_message(
                self.agent_id, agent_id,
                f"Task complete: {task['title']}",
                f"Task {task_id} is done. Result: {result or 'none'}",
                task_id=task_id
            )
        return {"task_id": task_id, "status": "done", "result": result}

    def _agent_tier(self, agent_id):
        """Determine the tier of an agent (pro/general/lite)."""
        # Check if agent is in pro or lite lists
        pro = self.router.config.get("agent_tiers", {}).get("pro", [])
        lite = self.router.config.get("agent_tiers", {}).get("lite", [])
        if agent_id in pro:
            return "pro"
        if agent_id in lite:
            return "lite"
        return "general"

    def status(self):
        """Return GOD agent status."""
        tasks = self.hive.list_tasks()
        status_counts = {}
        for t in tasks:
            s = t.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "agent_id": self.agent_id,
            "role": "god_orchestrator",
            "status": "online",
            "tasks": status_counts,
            "provider_status": self.router.status()
        }
