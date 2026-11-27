#!/usr/bin/env python3
"""
Faith Daily Runner - Called by launchd at 09:00 each day.

Orchestrates the full six-stage pipeline:
1. Faith Director picks next reel from queue
2. Faith Worker produces, verifies, publishes
3. Metrics recorded for adaptation
4. Heartbeat logged
"""
import os
import sys
import json
from pathlib import Path

# Add office-os to path
sys.path.insert(0, str(Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os")))))

from core.hive import Hive
from agents.faith_director import FaithDirector
from agents.faith_worker import FaithWorker


def main():
    print(f"[{__name__}] Starting faith daily runner at {__import__('datetime').datetime.now()}")
    
    hive = Hive()
    
    # Step 1: Faith Director picks next reel
    director = FaithDirector(hive=hive, router=None)
    result = director.run_round()
    
    print(f"[{__name__}] Director result: {result}")
    
    if result.get("status") == "no_queue":
        print(f"[{__name__}] No queue available, will regenerate next cycle")
        return
    
    if result.get("status") != "enqueued":
        print(f"[{__name__}] Director didn't enqueue a reel: {result}")
        return
    
    # Step 2: Faith Worker executes the task
    # Find the task the director just created
    task_id = result.get("task_id")
    if not task_id:
        print(f"[{__name__}] No task ID from director")
        return
    
    task = hive.get_task(task_id)
    if not task:
        print(f"[{__name__}] Task {task_id} not found")
        return
    
    print(f"[{__name__}] Worker executing task: {task['title']}")
    
    worker = FaithWorker(hive=hive, router=None)
    worker_result = worker.execute_task(task)
    
    print(f"[{__name__}] Worker result: {worker_result}")
    
    # Step 3: Record anything else
    if worker_result.get("status") == "done":
        print(f"[{__name__}] Reel published successfully: {worker_result.get('reel_id')}")
    elif worker_result.get("status") == "rejected":
        print(f"[{__name__}] Reel rejected by quality gates - director will pull next")
    elif worker_result.get("status") == "failed":
        print(f"[{__name__}] Reel production/publish failed")
    else:
        print(f"[{__name__}] Unexpected worker result: {worker_result}")
    
    # Step 4: Heartbeat / log
    director.heartbeat() if hasattr(director, 'heartbeat') else None
    
    print(f"[{__name__}] Faith daily cycle complete")


if __name__ == "__main__":
    main()
