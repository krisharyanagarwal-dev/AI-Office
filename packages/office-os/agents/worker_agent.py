"""
Worker Agent - executes tasks via direct provider API calls.
Bypasses OpenCode's full agent framework (~53K input tokens → ~3K).
Each worker maps to one OpenCode subagent from the 230-agent fleet.
Borrowed patterns from agent-swarm (worker delegation) and Munder Difflin.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.hive import Hive
from core.router import ProviderRouter
from core.provider_client import make_client, ProviderClient


class WorkerAgent:
    def __init__(self, agent_id, hive=None, router=None):
        self.agent_id = agent_id
        self.hive = hive or Hive()
        self.router = router or ProviderRouter()
        self.status = "idle"  # idle | busy | error
        self.current_task = None

        self.hive.remember(self.agent_id, "role", "worker", tags=["role", "worker"])
        self.hive.remember(self.agent_id, "status", "online", tags=["status"])

    def execute_task(self, task):
        """Execute a task via direct provider API call."""
        self.status = "busy"
        self.current_task = task["id"]
        task_id = task["id"]
        attempt = task.get("metadata", {}).get("retries", 0)
        self.hive.update_task(task_id, status="in_progress")
        self.hive.remember(self.agent_id, f"current_task_{task_id}", task["title"], tags=["task"])

        try:
            result = self._call_provider(task)
            # RACE CONDITION GUARD: re-read task to ensure the reaper hasn't
            # requeued it while we were working. If retries changed or status
            # isn't in_progress, another worker took over — skip writing.
            current = self.hive.get_task(task_id)
            if current is None:
                self.status = "idle"
                self.current_task = None
                return {"status": "skipped", "error": "task deleted"}
            if current.get("status") != "in_progress":
                self.status = "idle"
                self.current_task = None
                return {"status": "skipped", "error": f"task already {current.get('status')}"}
            current_retries = current.get("metadata", {}).get("retries", 0)
            if current_retries != attempt:
                self.status = "idle"
                self.current_task = None
                return {"status": "skipped", "error": f"retries changed {attempt}->{current_retries}"}

            self.hive.update_task(task_id, status="done", result=result)
            self.hive.send_message(
                self.agent_id, "michael",
                f"Task complete: {task['title']}",
                f"Task {task_id} completed by {self.agent_id}. Result: {str(result)[:200]}",
                task_id=task_id,
                user_id=task.get("user_id"),
            )
            self.hive.remember(self.agent_id, f"completed_{task_id}", result, tags=["completed_task"])
            return {"status": "done", "result": result}

        except Exception as e:
            error_msg = str(e)
            pool_name = task.get("assigned_pool")
            # HEALTH FEEDBACK: mark pool rate-limited or quota-exhausted
            if self._is_quota_exhausted(error_msg):
                self.router.mark_daily_quota_exceeded(pool_name)
            elif self._is_rate_limit_error(error_msg):
                self.router.mark_rate_limited(pool_name)

            # RACE CONDITION GUARD: same as success path — don't clobber a
            # task the reaper already requeued.
            current = self.hive.get_task(task_id)
            if current is not None and current.get("status") != "in_progress":
                self.status = "idle"
                self.current_task = None
                return {"status": "skipped", "error": f"task already {current.get('status')}"}

            self.hive.update_task(task_id, status="failed", error=error_msg)
            self.hive.send_message(
                self.agent_id, "michael",
                f"Task failed: {task['title']}",
                f"Task {task_id} failed: {error_msg}",
                task_id=task_id,
                user_id=task.get("user_id"),
            )
            self.status = "error"
            return {"status": "failed", "error": error_msg}

        finally:
            self.status = "idle"
            self.current_task = None

    def _call_provider(self, task):
        """
        Dispatch a task to a provider via direct API call.
        Tasks marked mode="act" are handed to the executor instead: they change a
        git worktree, and the result is kept only if the diff gate passes.
        The agent_id maps to a file in ~/.config/opencode/agent/ which has
        the agent's system prompt (operating rules, output contract).
        We prepend the agent's rules to the task prompt.
        """
        if (task.get("metadata") or {}).get("mode") == "act":
            from core.executor import run_act_task
            return run_act_task(task)

        # Read the agent's system prompt from its .md file
        agent_prompt = self._load_agent_prompt()

        # Build the full prompt: agent rules + task
        full_prompt = self._build_prompt(agent_prompt, task)

        # Get the provider/model assignment from the task
        pool_name = task.get("assigned_pool")
        model = task.get("assigned_model")

        if not pool_name or not model:
            # Router assigns a provider if not pre-assigned
            tier = self._agent_tier()
            pool_name, model = self.router.select_provider(tier=tier)
            if not pool_name:
                raise RuntimeError("No providers available")

        client = make_client(pool_name, model)
        priority = task.get("priority", "normal")
        try:
            response = client.complete(full_prompt, max_tokens=4096, temperature=0, priority=priority)
        except ProviderClient.PoolUnavailable as e:
            # curl timeout → mark pool rate-limited so router routes elsewhere
            self.router.mark_rate_limited(pool_name)
            raise RuntimeError(str(e))

        return response

    @staticmethod
    def _is_rate_limit_error(msg):
        """Detect rate-limit / quota / credit exhaustion errors."""
        lower = msg.lower()
        rate_keywords = [
            "rate limit", "ratelimit", "rate_limit",
            "quota", "exceeded", "credit", "payment_required",
            "billing", "insufficient", "too many requests",
            "tpm", "rpd", "tokens per minute",
            "timeout",
        ]
        return any(k in lower for k in rate_keywords)

    @staticmethod
    def _is_quota_exhausted(msg):
        """Detect daily quota exhaustion errors (longer cooldown needed)."""
        lower = msg.lower()
        quota_keywords = [
            "quota exceeded", "daily quota", "monthly quota",
            "usage limit", "usage exceeded", "resource exhausted",
            "rate limit exceeded.*daily", "daily rate limit",
        ]
        return any(k in lower for k in quota_keywords)

    def _load_agent_prompt(self):
        """Load the agent's system prompt from its .md file."""
        agent_path = Path(f"/Users/aryanagarwal/.config/opencode/agent/{self.agent_id}.md")
        if not agent_path.exists():
            # Fallback: no agent file, use generic prompt
            return "You are a helpful assistant. Execute the task described below."
        try:
            content = agent_path.read_text()
            # Extract the body (after frontmatter)
            if content.startswith("---\n"):
                parts = content.split("---\n", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
        except Exception:
            return "You are a helpful assistant. Execute the task described below."

    def _build_prompt(self, agent_prompt, task):
        """Build the full prompt for the provider."""
        return f"""{agent_prompt}

Execute this task:

Task: {task['title']}
Description: {task['description']}
Priority: {task.get('priority', 'normal')}
Task ID: {task['id']}
User: {task.get('user_id', 'unknown')}

Produce a complete, well-structured result. Include any files created, decisions made, and next steps.

CRITICAL: Output only the final answer — no reasoning, planning, step-by-step analysis, chain-of-thought, or preamble. Start directly with your answer."""

    def _agent_tier(self):
        """Determine the tier of this agent."""
        pro = self.router.config.get("agent_tiers", {}).get("pro", [])
        lite = self.router.config.get("agent_tiers", {}).get("lite", [])
        if self.agent_id in pro:
            return "pro"
        if self.agent_id in lite:
            return "lite"
        return "general"

    def get_inbox(self):
        return self.hive.get_inbox(self.agent_id, unread_only=True)

    def mark_read(self, msg_id):
        self.hive.mark_read(self.agent_id, msg_id)

    def send_message(self, to_agent, subject, body, task_id=None, user_id=None):
        return self.hive.send_message(self.agent_id, to_agent, subject, body, task_id, user_id)

    def status_report(self):
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "current_task": self.current_task,
            "inbox_count": len(self.get_inbox()),
        }
