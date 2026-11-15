"""
Autopilot - the office prompts its own models instead of waiting for a human.

One "round", run on a timer while the office is idle:
  1. Michael (the god agent) asks a model to write one tailored question per agent.
  2. Michael sends each agent its question; each agent's model answers in role.
  3. Michael asks a model to synthesise the replies into a round-up for the human.

Everything goes through the hive mailbox, so the conversation is visible in the
usual inbox/outbox files, and each round is also saved as logs/autopilot/*.md.

Bounded on purpose: one round per interval, a daily cap, only when no tasks are
queued or running, and it never creates tasks unless config says so.
"""
import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from core.provider_client import make_client

ROOT = Path("/Users/aryanagarwal/office-os")
STATE_PATH = ROOT / "config" / "autopilot_state.json"
ROUNDS_DIR = ROOT / "logs" / "autopilot"
AGENT_DIR = Path("/Users/aryanagarwal/.config/opencode/agent")

DEFAULTS = {
    "enabled": False,
    "interval_min": 30,
    "max_rounds_per_day": 24,
    "startup_delay_sec": 60,
    "topic": (
        "Look at what this office has recently done and say what the single most "
        "valuable next piece of work in your specialty would be, and why."
    ),
    "create_tasks": False,
    "max_reply_tokens": 2000,
    "parallel_agents": 3,
    "call_timeout_sec": 150,
    "problem_tasks_per_round": 3,
}

# Several of the free models think out loud and, when they run out of tokens,
# the provider hands back that thinking as if it were the reply. Requiring a
# marker lets us keep only the real answer and treat a missing one as no reply.
# Tempered so a block starts at the nearest opening tag: a model quoting the
# tag while thinking must not swallow the real answer that follows.
ANSWER_RE = re.compile(r"<answer>((?:(?!<answer>).)*?)</answer>", re.S | re.I)
ANSWER_RULE = (
    "Put your final answer between <answer> and </answer> tags. Only the text "
    "inside the last complete pair of tags is kept; everything else is discarded."
)


def extract_answer(text):
    """Return the last complete, non-trivial <answer> block, or None. A model that
    was cut off mid-thought has no closed block, so it counts as no reply instead
    of having its thinking passed off as an answer."""
    blocks = [b.strip() for b in ANSWER_RE.findall(text or "")]
    blocks = [b for b in blocks if len(b) >= 15]
    return blocks[-1] if blocks else None


STOP_FILE = ROOT / "STOP"


def stop_requested():
    """Kill switch: `touch ~/office-os/STOP` halts rounds and act-tasks on the next poll."""
    return STOP_FILE.exists()


class Autopilot:
    def __init__(self, hive, router, god, workers, config):
        self.hive = hive
        self.router = router
        self.god = god
        self.workers = workers  # live dict owned by the orchestrator
        self.cfg = {**DEFAULTS, **(config or {})}
        self.started_at = time.time()
        self._thread = None
        self._next_net_check = 0
        self._offline_logged = False
        self.state = self._load_state()

    # ---------- scheduling ----------
    def due(self, office_idle):
        """True when a round should start now."""
        if not self.cfg["enabled"] or not office_idle or not self.workers:
            return False
        if stop_requested():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        now = time.time()
        if now - self.started_at < self.cfg["startup_delay_sec"]:
            return False
        if now - self.state.get("last_round_ts", 0) < self.cfg["interval_min"] * 60:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("day") == today and self.state.get("rounds_today", 0) >= self.cfg["max_rounds_per_day"]:
            return False
        # No network (laptop asleep, off wifi): wait instead of burning a round
        # and cooling down every pool. Re-check at most once a minute.
        if now < self._next_net_check:
            return False
        if not self._online():
            self._next_net_check = now + 60
            if not self._offline_logged:
                print("[autopilot] Offline - rounds paused until the network is back")
                self._offline_logged = True
            return False
        self._offline_logged = False
        return True

    @staticmethod
    def _online():
        try:
            socket.create_connection(("integrate.api.nvidia.com", 443), timeout=5).close()
            return True
        except OSError:
            return False

    def start_round(self):
        """Run a round on a background thread so the main loop keeps polling."""
        # Stamp the attempt first: a round that fails must still wait out the
        # interval instead of retrying every poll.
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("day") != today:
            self.state["day"] = today
            self.state["rounds_today"] = 0
        self.state["rounds_today"] = self.state.get("rounds_today", 0) + 1
        self.state["last_round_ts"] = time.time()
        self._save_state()
        self._thread = threading.Thread(target=self._safe_round, name="autopilot", daemon=True)
        self._thread.start()

    def _safe_round(self):
        try:
            self.run_round()
        except Exception as e:  # never let a round take the orchestrator down
            print(f"[autopilot] Round failed: {e}")
            self.hive._emit_event("autopilot_round_failed", error=str(e))

    # ---------- one round ----------
    def _next_department(self):
        """Rotate through the configured departments, skipping any with no registered lead."""
        depts = self.cfg.get("departments") or []
        for _ in range(len(depts)):
            idx = self.state.get("dept_index", 0) % len(depts)
            self.state["dept_index"] = idx + 1
            dept = depts[idx]
            leads = [a for a in dept.get("leads", []) if a in self.workers]
            if leads:
                return dept, leads
        return None, list(self.workers.keys())

    def run_round(self):
        dept, agents = self._next_department()
        topic = dept["brief"] if dept else self.cfg["topic"]
        boss = self.god.agent_id
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dept_name = dept["id"] if dept else "general"
        print(f"[autopilot] Round {stamp} ({dept_name}) started with {len(agents)} agents")
        self.hive._emit_event("autopilot_round_started", round=stamp, agents=agents)

        context = self._office_context()
        questions = self._write_questions(agents, context, topic)

        def talk(agent_id):
            question = questions.get(agent_id) or topic
            sent = self.hive.send_message(boss, agent_id, f"Check-in {stamp}", question)
            try:
                answer, pool, model = self._ask(
                    self._tier(agent_id),
                    self._agent_prompt(agent_id, question, context),
                    self.cfg["max_reply_tokens"],
                )
                reply = {"question": question, "answer": answer, "via": f"{pool}/{model}"}
                self.hive.send_message(agent_id, boss, f"Re: Check-in {stamp}", answer)
                print(f"[autopilot] {agent_id} replied via {pool}/{model}")
            except Exception as e:
                reply = {"question": question, "answer": None, "error": str(e)}
                print(f"[autopilot] {agent_id} did not reply: {e}")
            self.hive.mark_read(agent_id, sent["id"])
            return reply

        with ThreadPoolExecutor(max_workers=max(1, int(self.cfg["parallel_agents"]))) as pool_exec:
            replies = dict(zip(agents, pool_exec.map(talk, agents)))

        answered = {a: r for a, r in replies.items() if r.get("answer")}
        summary = None
        if answered:
            try:
                summary, pool, model = self._ask_manager(self._summary_prompt(answered, context), self.cfg["max_reply_tokens"])
                self.hive.send_message(boss, "human", f"Office round-up {stamp}", summary)
            except Exception as e:
                print(f"[autopilot] Round-up failed: {e}")

        created = []
        if summary and self.cfg["create_tasks"]:
            created = self._create_followup_task(summary, stamp)
        if self.cfg["create_tasks"]:
            created += self._file_problem_tasks(stamp)

        self._write_round_file(stamp, replies, summary, created)
        self.hive._emit_event(
            "autopilot_round_finished", round=stamp,
            answered=len(answered), asked=len(agents), summarised=bool(summary),
        )
        print(f"[autopilot] Round {stamp} ({dept_name}) finished: {len(answered)}/{len(agents)} agents answered, "
              f"round-up {'sent to human inbox' if summary else 'not produced'}")

    # ---------- prompts ----------
    def _office_context(self):
        done = self.hive.list_tasks(status="done")[-5:]
        failed = self.hive.list_tasks(status="failed")[-3:]
        lines = ["Recently completed tasks:"]
        lines += [f"- {t['title']} (by {t.get('agent_id')}): {str(t.get('result'))[:300]}" for t in done] or ["- none"]
        if failed:
            lines.append("Recently failed tasks:")
            lines += [f"- {t['title']}: {str(t.get('error'))[:200]}" for t in failed]
        lines.append(self._org_digest())
        prev = self.state.get("last_summary")
        if prev:
            lines.append("Previous round-up (do not repeat it, build on it):")
            lines.append(prev[:1200])
        return "\n".join(lines)

    @staticmethod
    def _org_digest():
        """Real state of the other systems, so questions are about actual problems.
        Imported lazily: the orchestrator imports this module, not the reverse."""
        try:
            from core.orchestrator import load_org_digest
            return load_org_digest()
        except Exception as e:
            return f"Organisation state: unavailable ({e})."

    def _write_questions(self, agents, context, topic):
        """Michael's model writes one question per agent. Falls back to the topic."""
        prompt = (
            "You are Michael, the manager of a small office of AI specialists.\n"
            f"Standing focus: {topic}\n\n{context}\n\n"
            "Write ONE short, specific question for each specialist below, fitted to "
            "their role and to the context above. The answer must be a single JSON "
            "object mapping each agent id to its question.\n"
            f"Agent ids: {json.dumps(agents)}\n" + ANSWER_RULE
        )
        try:
            text, pool, model = self._ask_manager(prompt, self.cfg["max_reply_tokens"])
            match = re.search(r"\{.*\}", text, re.S)
            parsed = json.loads(match.group(0)) if match else {}
            questions = {a: str(parsed[a]).strip() for a in agents if isinstance(parsed.get(a), str) and parsed[a].strip()}
            print(f"[autopilot] Michael wrote {len(questions)}/{len(agents)} questions via {pool}/{model}")
            return questions
        except Exception as e:
            print(f"[autopilot] Question writing failed, using the standing topic: {e}")
            return {}

    def _agent_prompt(self, agent_id, question, context):
        return (
            f"{self._load_role(agent_id)}\n\n"
            f"You are '{agent_id}' in an office of AI specialists. Your manager Michael asks:\n"
            f"{question}\n\n{context}\n\n"
            "Answer in your role, in at most 120 words, concretely. If you have nothing "
            "useful to add, say so in one sentence.\n" + ANSWER_RULE
        )

    def _summary_prompt(self, answered, context):
        body = "\n\n".join(f"[{a}] asked: {r['question']}\nanswered: {r['answer']}" for a, r in answered.items())
        return (
            "You are Michael, the office manager. Your specialists replied to your check-in:\n\n"
            f"{body}\n\n{context}\n\n"
            "Write a round-up for the human owner in at most 150 words: where the "
            "specialists agree, where they disagree, and the ONE next task you recommend "
            "with the agent who should do it. Be honest if the replies were thin.\n" + ANSWER_RULE
        )

    def _load_role(self, agent_id):
        path = AGENT_DIR / f"{agent_id}.md"
        try:
            content = path.read_text()
            if content.startswith("---\n"):
                parts = content.split("---\n", 2)
                if len(parts) >= 3:
                    content = parts[2]
            return content.strip()[:4000]
        except OSError:
            return "You are a helpful specialist."

    # ---------- model calls ----------
    def _ask(self, tier, prompt, max_tokens):
        """Call a model, moving to another pool on failure. Returns (text, pool, model)."""
        last_error = None
        for _ in range(3):
            pool, model = self.router.select_provider(tier=tier)
            if not pool:
                break
            try:
                text = make_client(pool, model).complete(
                    prompt, max_tokens=max_tokens, temperature=0.3,
                    priority="low", timeout=self.cfg["call_timeout_sec"])
                answer = extract_answer(text)
                if answer:
                    return answer, pool, model
                last_error = f"{pool}/{model} gave no final answer (reasoning only or cut off)"
                continue  # a bad answer is not a rate limit: try another pool, no cooldown
            except Exception as e:
                last_error = str(e)
                # curl 6/7 = cannot resolve/connect: our network, not their limit.
                if "curl failed (exit 6)" in last_error or "curl failed (exit 7)" in last_error:
                    raise RuntimeError(f"network down ({last_error.strip()})")
            self.router.mark_rate_limited(pool)
        raise RuntimeError(f"no provider answered ({last_error or 'none available'})")

    def _ask_manager(self, prompt, max_tokens):
        """Michael's own calls: try the pro pools, then fall back to general ones."""
        try:
            return self._ask("pro", prompt, max_tokens)
        except RuntimeError:
            return self._ask("general", prompt, max_tokens)

    def _tier(self, agent_id):
        tiers = self.router.config.get("agent_tiers", {})
        if agent_id in tiers.get("pro", []):
            return "pro"
        if agent_id in tiers.get("lite", []):
            return "lite"
        return "general"

    # ---------- outputs ----------
    def _create_followup_task(self, summary, stamp):
        """Turn the round-up's recommendation into one task, assigned to the agent
        it names (the last registered agent mentioned), else left for auto-assign."""
        mentioned = [(summary.rfind(a), a) for a in self.workers if a in summary]
        agent_id = max(mentioned)[1] if mentioned else None
        outcome = self.god.create_task(
            f"Autopilot follow-up {stamp}",
            "Carry out the next task recommended in this round-up. Produce the actual "
            f"deliverable, not a plan to produce it.\n\n{summary}",
            agent_id=agent_id, priority="low", user_id="aryan",
        )
        task_id = outcome.get("task_id") or (outcome.get("task") or {}).get("id")
        print(f"[autopilot] Created follow-up task {task_id} for {agent_id or 'auto-assign'}")
        return [f"{task_id} -> {agent_id or 'auto-assign'}"] if task_id else []

    def _file_problem_tasks(self, stamp):
        """Open at most one task per recurring problem in the organisation survey.
        The key is the problem text with digits masked, so a counter ticking from
        12 to 13 does not file a second task. A key is forgotten once its problem
        clears, so a problem that comes back gets a fresh task."""
        import hashlib
        try:
            doc = json.loads((ROOT / "logs" / "org_state.json").read_text())
        except (OSError, json.JSONDecodeError):
            return []
        keys = self.state.setdefault("problem_keys", {})
        current = {}
        for system in doc.get("systems", []):
            for problem in system.get("problems", []):
                norm = re.sub(r"\d+", "#", f"{system.get('name')}|{problem}")
                current[hashlib.sha1(norm.encode()).hexdigest()[:12]] = (system.get("name"), problem)
        for key in list(keys):
            if key not in current:
                del keys[key]
        dept = next((d for d in self.cfg.get("departments", []) if d.get("id") == "fleet-health"), None)
        lead = next((a for a in (dept or {}).get("leads", []) if a in self.workers), None)
        created = []
        for key, (name, problem) in current.items():
            if key in keys or len(created) >= int(self.cfg["problem_tasks_per_round"]):
                continue
            outcome = self.god.create_task(
                f"Fix: {name}: {problem[:70]}",
                f"The organisation survey reports this problem in {name}:\n\n{problem}\n\n"
                "Diagnose the cause from the evidence you have, then state the exact next check or fix. "
                "Do not claim it is fixed unless you verified it.",
                agent_id=lead, priority="normal", user_id="aryan",
            )
            task_id = outcome.get("task_id") or (outcome.get("task") or {}).get("id")
            if task_id:
                keys[key] = task_id
                created.append(f"{task_id} -> {lead or 'auto-assign'} ({name})")
                print(f"[autopilot] Filed problem task {task_id} for {name} (round {stamp})")
        self._save_state()
        return created

    def _write_round_file(self, stamp, replies, summary, created):
        ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        out = [f"# Autopilot round {stamp}", "", "## Round-up", "", summary or "_No round-up was produced._", ""]
        for agent_id, r in replies.items():
            out += [f"## {agent_id}", "", f"**Asked:** {r['question']}", ""]
            if r.get("answer"):
                out += [r["answer"], "", f"_via {r['via']}_", ""]
            else:
                out += [f"_No reply: {r.get('error')}_", ""]
        if created:
            out += ["## Tasks created", ""] + [f"- {t}" for t in created]
        (ROUNDS_DIR / f"round-{stamp}.md").write_text("\n".join(out))
        if summary:
            self.state["last_summary"] = summary
            self._save_state()

    def _load_state(self):
        try:
            return json.loads(STATE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        tmp.replace(STATE_PATH)
