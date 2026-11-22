"""
Orchestrator - main event loop for Office OS.
Runs 24/7: polls tasks, assigns workers, runs heartbeat, monitors health.
Uses ThreadPoolExecutor for concurrent task execution (non-blocking).
Includes stuck-task reaper with timeout and retry logic.
"""
import calendar
import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent
from agents.worker_agent import WorkerAgent
from core.intake import process_inbox
from core.autopilot import Autopilot
from core.sources import collect_all
import threading

# logs/ is the ONE part of ~/office-os that is a real directory rather than a
# symlink into this monorepo, so deriving it from __file__ would silently move
# the orchestrator's state into packages/office-os/logs/ and abandon the live
# org_state.json. Honour OFFICE_OS_HOME instead: default keeps the laptop
# byte-identical, and the mini's plist points it at that checkout.
OFFICE_OS_HOME = Path(os.environ.get("OFFICE_OS_HOME") or (Path.home() / "office-os"))
ORG_STATE_PATH = OFFICE_OS_HOME / "logs" / "org_state.json"
ORG_REFRESH_SEC = 300


def write_org_state(results, path=ORG_STATE_PATH):
    """Write the org digest atomically (tmp + os.replace) so readers never see a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "systems": results,
        "all_ok": all(r.get("ok") for r in results),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, path)
    return doc


def load_org_digest(path=ORG_STATE_PATH, max_age_sec=ORG_REFRESH_SEC * 3):
    """Short text digest of the org state for the autopilot. Stale or missing -> says so."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return "Organisation state: unavailable (no recent system survey)."
    age = time.time() - calendar.timegm(time.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    if age > max_age_sec:
        return f"Organisation state: STALE (last survey {age / 60:.0f} min ago), treat as unknown."
    lines = ["Organisation state:"]
    for s in doc.get("systems", []):
        status = "OK" if s.get("ok") else "PROBLEM"
        lines.append(f"- {s['name']}: {status}. {s.get('summary', '')}")
        for p in s.get("problems", [])[:3]:
            lines.append(f"    * {p}")
    return "\n".join(lines)


def acquire_lock(lock_path: str) -> bool:
    """Try to acquire a lock file. Returns True if we got it, False if already held."""
    lock = Path(lock_path)
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            # Check if process is still alive
            os.kill(pid, 0)
            return False  # Process is running, lock is held
        except (ValueError, OSError, ProcessLookupError):
            # Stale lock file, remove it
            lock.unlink(missing_ok=True)
    try:
        lock.write_text(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock(lock_path: str):
    """Remove the lock file if we hold it."""
    try:
        Path(lock_path).unlink(missing_ok=True)
    except OSError:
        pass


class Orchestrator:
    def __init__(self, config_path=None):
        # Default resolves next to this checkout, so the orchestrator runs
        # under any home -- it used to hardcode /Users/aryanagarwal. Kept as
        # str: ProviderRouter and the config readers take the path as text.
        if config_path is None:
            config_path = str(Path(__file__).resolve().parents[1] / "config" / "office.json")
        self.config_path = config_path
        with open(config_path) as f:
            self.config = json.load(f)

        self.hive = Hive()
        from core.mini_bridge import MiniBridge
        self.mini_bridge = MiniBridge(self.hive)
        self.router = ProviderRouter(config_path)
        self.god = GodAgent(self.hive, self.router)
        self.workers = {}  # agent_id -> WorkerAgent

        self.running = False
        self.task_poll_interval = self.config["office"]["task_poll_interval_sec"]
        self.heartbeat_interval = self.config["office"]["heartbeat_interval_sec"]
        self.max_workers = self.config["office"]["max_concurrent_workers"]
        self.max_retries = self.config["office"]["max_retries_per_task"]
        self.task_timeout_sec = self.config["office"].get("task_timeout_sec", 600)
        self.last_heartbeat = 0

        # Thread pool for concurrent task execution
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.running_futures = {}  # future -> (task_id, agent_id, start_time, attempt)

        # Self-prompting rounds: Michael questions every registered agent on a timer.
        self.autopilot = Autopilot(self.hive, self.router, self.god, self.workers,
                                   {**(self.config.get("autopilot") or {}),
                                    "departments": self.config.get("departments", [])})

        # Organisation survey: refreshed on a background thread so a slow
        # system (the mini's ssh can take 15s) never stalls the main loop.
        self._org_thread = None
        self._last_org_refresh = 0.0

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        print("\n[orchestrator] Shutting down gracefully...")
        self.running = False

    def _get_available_worker(self):
        """Find an idle worker, or None if all busy."""
        for agent_id, worker in self.workers.items():
            if worker.status == "idle":
                return worker
        return None

    def _register_worker(self, agent_id):
        """Register a new worker agent."""
        if agent_id not in self.workers:
            self.workers[agent_id] = WorkerAgent(agent_id, self.hive, self.router)
            print(f"[orchestrator] Worker registered: {agent_id}")

    def _run_mini_bridge(self):
        now = time.time()
        if now - getattr(self, "_mini_last", 0) < 60:
            return
        self._mini_last = now
        try:
            report = self.mini_bridge.cycle()
            if report.get("delivered") or report.get("collected"):
                print(f"[orchestrator] mini bridge: {report}")
        except Exception as e:  # the bridge must never stop the office loop
            print(f"[orchestrator] mini bridge error: {type(e).__name__}: {str(e)[:160]}")

    def _auto_assign_pending(self):
        """Auto-assign pending tasks to idle workers."""
        pending = self.hive.list_tasks(status="pending")
        for task in pending:
            if (task.get("metadata") or {}).get("target") == "mini":
                continue  # owned by the mini bridge until its verdict arrives
            worker = self._get_available_worker()
            if not worker:
                break  # No idle workers, wait
            self.god.assign_task(task["id"], worker.agent_id)

    def _execute_assigned_tasks(self):
        """Execute assigned tasks on idle workers (non-blocking via thread pool)."""
        assigned = self.hive.list_tasks(status="assigned")
        for task in assigned:
            agent_id = task.get("agent_id")
            if not agent_id:
                continue

            # Register worker if not already registered
            if agent_id not in self.workers:
                self._register_worker(agent_id)

            worker = self.workers[agent_id]
            if worker.status != "idle":
                continue  # Worker busy

            task_id = task["id"]

            # Check if this task already has a running future
            if any(f_task_id == task_id for f_task_id in self.running_futures.values()):
                continue

            # Check retry count
            retries = task.get("metadata", {}).get("retries", 0)
            if retries >= self.max_retries:
                print(f"[orchestrator] Task {task_id} exceeded max retries ({self.max_retries}), escalating")
                self.god.escalate(task_id, "Exceeded max retries")
                continue

            print(f"[orchestrator] Worker {agent_id} executing task {task_id}: {task['title']} (attempt {retries + 1})")
            future = self.executor.submit(worker.execute_task, task)
            self.running_futures[future] = (task_id, agent_id, time.time(), retries + 1)

        # Check for completed futures
        if not self.running_futures:
            return

        done_futures, _ = wait(self.running_futures.keys(), timeout=0, return_when=FIRST_COMPLETED)

        for future in list(done_futures):
            task_id, agent_id, start_time, attempt = self.running_futures.pop(future)
            try:
                result = future.result()
                if result.get("status") == "done":
                    print(f"[orchestrator] Task {task_id} completed by {agent_id}")
                else:
                    print(f"[orchestrator] Task {task_id} failed by {agent_id}: {result.get('error', 'unknown')}")
                    self._handle_task_failure(task_id, agent_id, attempt)
            except Exception as e:
                print(f"[orchestrator] Task {task_id} by {agent_id} raised exception: {e}")
                self._handle_task_failure(task_id, agent_id, attempt)

    def _handle_task_failure(self, task_id, agent_id, attempt):
        """Handle a failed task: retry on different worker or escalate."""
        t = self.hive.get_task(task_id)
        if not t:
            return

        retries = t.get("metadata", {}).get("retries", 0)

        if attempt < self.max_retries:
            # Reassign to a different worker
            print(f"[orchestrator] Requeueing task {task_id} (retry {attempt}/{self.max_retries})")
            self.hive.update_task(
                task_id,
                status="pending",
                agent_id=None,
                assigned_pool=None,
                assigned_model=None,
                metadata={**t.get("metadata", {}), "retries": attempt + 1, "last_error_agent": agent_id},
            )
        else:
            # Max retries reached, escalate
            print(f"[orchestrator] Task {task_id} exceeded max retries, escalating")
            self.god.escalate(task_id, f"Failed after {self.max_retries} attempts")

    def _reap_stuck_tasks(self):
        """Reap tasks stuck in 'in_progress' beyond the timeout."""
        now = time.time()
        stuck = []
        for future, (task_id, agent_id, start_time, attempt) in list(self.running_futures.items()):
            if now - start_time > self.task_timeout_sec:
                print(f"[orchestrator] Task {task_id} by {agent_id} stuck for {now - start_time:.0f}s, reaping")
                future.cancel()  # Best effort - thread can't be killed, but we stop tracking it
                stuck.append((future, task_id, agent_id, attempt))

        for future, task_id, agent_id, attempt in stuck:
            self.running_futures.pop(future, None)
            self._handle_task_failure(task_id, agent_id, attempt)

    def _check_task_completion(self):
        """Check if any in_progress tasks have result files (worker wrote them)."""
        # Workers write results via hive.update_task, so we just monitor status
        pass

    def _refresh_org_state(self):
        """Kick off a survey of the other office systems if one is due."""
        if self._org_thread is not None and self._org_thread.is_alive():
            return
        if time.time() - self._last_org_refresh < ORG_REFRESH_SEC:
            return
        self._last_org_refresh = time.time()

        def _survey():
            try:
                doc = write_org_state(collect_all())
                bad = [s["name"] for s in doc["systems"] if not s.get("ok")]
                print(f"[orchestrator] Org survey: {len(doc['systems']) - len(bad)}/{len(doc['systems'])} ok"
                      + (f"; problems in {', '.join(bad)}" if bad else ""))
            except Exception as e:
                print(f"[orchestrator] Org survey failed: {e}")

        self._org_thread = threading.Thread(target=_survey, name="org-survey", daemon=True)
        self._org_thread.start()

    def _run_heartbeat(self):
        """Run heartbeat if interval elapsed."""
        now = time.time()
        if now - self.last_heartbeat >= self.heartbeat_interval:
            result = self.god.run_heartbeat()
            self.last_heartbeat = now
            return result
        return None

    def _register_default_workers(self):
        """Register default workers from pro and lite tiers."""
        pro_agents = self.router.config.get("agent_tiers", {}).get("pro", [])
        lite_agents = self.router.config.get("agent_tiers", {}).get("lite", [])

        for agent_id in pro_agents[:self.max_workers]:
            self._register_worker(agent_id)

        for agent_id in lite_agents[:2]:
            self._register_worker(agent_id)

        # Department leads must be live workers, or the autopilot cannot ask them.
        for dept in self.config.get("departments", []):
            for agent_id in dept.get("leads", []):
                self._register_worker(agent_id)

    def run(self):
        """Main event loop - runs until shutdown."""
        # Acquire lock to prevent double-running
        lock_path = str(OFFICE_OS_HOME / "logs" / "orchestrator.lock")
        if not acquire_lock(lock_path):
            print("[orchestrator] Another instance is already running. Exiting.")
            return

        self.running = True
        print(f"[orchestrator] Office OS started. God agent: {self.god.agent_id}")
        print(f"[orchestrator] Max workers: {self.max_workers}")
        print(f"[orchestrator] Task timeout: {self.task_timeout_sec}s")
        print(f"[orchestrator] Max retries: {self.max_retries}")
        print(f"[orchestrator] Heartbeat every {self.heartbeat_interval}s")
        print(f"[orchestrator] Provider pools: {list(self.router.pools.keys())}")

        self._register_default_workers()
        print(f"[orchestrator] Workers: {list(self.workers.keys())}")

        # Log startup
        self.hive._emit_event("orchestrator_started", max_workers=self.max_workers)

        try:
            while self.running:
                try:
                    # 1. Auto-assign pending tasks to idle workers
                    self._auto_assign_pending()

                    # 2. Execute assigned tasks on idle workers (non-blocking)
                    self._execute_assigned_tasks()

                    # 3. Reap stuck tasks
                    self._reap_stuck_tasks()

                    # 4. Run heartbeat
                    hb = self._run_heartbeat()
                    if hb:
                        print(f"[orchestrator] Heartbeat: {hb['inbox_processed']} messages processed")

                    # 4a. Organisation survey (background, every ORG_REFRESH_SEC)
                    self._refresh_org_state()
                    # 4a2. Mini bridge: deliver queued mini tasks, collect verdicts (at most once a minute)
                    self._run_mini_bridge()

                    # 4b. Intake watcher - scan for new .md files in inbox dir
                    try:
                        process_inbox(self.hive, self.router, self.god)
                    except Exception as e:
                        print(f"[orchestrator] Intake error: {e}")

                    # 5. Check worker status and report
                    for agent_id, worker in self.workers.items():
                        report = worker.status_report()
                        if report["status"] == "error":
                            print(f"[orchestrator] Worker {agent_id} in error state")
                            worker.status = "idle"
                            worker.current_task = None

                    # 6. Print status summary
                    pending_count = len(self.hive.list_tasks(status="pending"))
                    in_progress_count = len(self.hive.list_tasks(status="in_progress"))
                    done_count = len(self.hive.list_tasks(status="done"))
                    failed_count = len(self.hive.list_tasks(status="failed"))
                    # Only log when the counts change, so an idle office doesn't
                    # write the same line every poll and grow the log forever.
                    counts = (pending_count, in_progress_count, done_count, failed_count)
                    if counts != getattr(self, "_last_logged_counts", None):
                        self._last_logged_counts = counts
                        print(f"[orchestrator] Tasks: {pending_count} pending, {in_progress_count} in_progress, {done_count} done, {failed_count} failed")

                    # 7. Autopilot: when nothing is queued or running, let the
                    # office prompt its own models and talk to every agent.
                    office_idle = (pending_count == 0 and in_progress_count == 0
                                   and not self.running_futures
                                   and not self.hive.list_tasks(status="assigned"))
                    if self.autopilot.due(office_idle):
                        self.autopilot.start_round()

                    time.sleep(self.task_poll_interval)

                except Exception as e:
                    print(f"[orchestrator] Error in loop: {e}")
                    time.sleep(self.task_poll_interval)

        finally:
            # Wait for running futures to complete
            print("[orchestrator] Waiting for running tasks to complete...")
            self.executor.shutdown(wait=True)
            self.hive._emit_event("orchestrator_stopped")
            print("[orchestrator] Stopped.")
            release_lock(lock_path)

    def status(self):
        """Return current orchestrator status."""
        tasks = self.hive.list_tasks()
        status_counts = {}
        for t in tasks:
            s = t.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        worker_status = {}
        for aid, w in self.workers.items():
            worker_status[aid] = w.status_report()

        return {
            "orchestrator": "running" if self.running else "stopped",
            "god_agent": self.god.agent_id,
            "tasks": status_counts,
            "workers": worker_status,
            "providers": self.router.status(),
            "running_futures": len(self.running_futures),
        }


def main():
    orch = Orchestrator()
    orch.run()


if __name__ == "__main__":
    main()
