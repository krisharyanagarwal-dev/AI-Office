#!/usr/bin/env python3
"""
Phase 2: Central Task Registry

Creates a persistent SQLite task database with UUIDs, status tracking,
deadlines, dependencies, and classification data.

Per the master prompt Section 5 (Autonomous Task Execution) Step 3 — ASSIGN:
"Choose the most suitable existing agent" — requires persistent task records.

Also per Section 5 Step 5 — MONITOR: "Track progress, deadlines and failures."

This script is a non-destructive first implementation step — it creates a task
database; no dispatch logic changes yet, no classification pipeline integration
yet. Rollback: delete the database; original company_dispatcher.py unchanged.
"""

import sqlite3
import uuid
import time
from pathlib import Path

DB_PATH = Path("/Users/aryanagarwal/AI-Office/packages/office-core/tasks.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    original_task TEXT NOT NULL,
    department TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'ACTIONABLE',
    status TEXT NOT NULL DEFAULT 'queued',
    assigned_agent TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    deadline TEXT,
    dependencies TEXT DEFAULT '[]',
    dependents TEXT DEFAULT '[]',
    classification_data TEXT DEFAULT '{}',
    output_evidence TEXT,
    verification_status TEXT DEFAULT 'pending',
    verification_evidence TEXT,
    cost_deduction REAL DEFAULT 0.0,
    note TEXT
)
"""

def init_db(db_path: Path = DB_PATH) -> Path:
    """Initialize the task database with the schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Task database initialized at: {db_path}")
    return db_path


def create_task(
    original_task: str,
    department: str,
    classification: str = "ACTIONABLE",
    deadline: str | None = None,
    dependencies: list | None = None,
    db_path: Path = DB_PATH,
) -> dict:
    """Create a new task record in the central registry."""
    task_id = f"c-{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    dept_options = ["research", "trading", "fleet", "upgrade", "ops", "assistant"]
    if department not in dept_options:
        print(f"Warning: Department '{department}' not in standard list. Using 'assistant' as default.")
        department = "assistant"
    
    deps_json = "[" + ", ".join(f"'{d}'" if isinstance(d, str) else str(d) for d in (dependencies or [])) + "]"
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO tasks 
           (task_id, original_task, department, classification, status, 
            assigned_agent, created_at, started_at, completed_at, 
            deadline, dependencies, dependents, classification_data, 
            output_evidence, verification_status, verification_evidence, 
            cost_deduction, note)
           VALUES 
           (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            original_task,
            department,
            classification,
            "queued",
            None,
            now,
            None,
            None,
            deadline,
            deps_json,
            "[]",
            "{}",
            None,
            "pending",
            None,
            0.0,
            None,
        ),
    )
    conn.commit()
    conn.close()
    
    task_record = {
        "task_id": task_id,
        "original_task": original_task,
        "department": department,
        "classification": classification,
        "status": "queued",
        "created_at": now,
        "deadline": deadline,
        "dependencies": dependencies or [],
    }
    
    print(f"Task created: {task_id}")
    print(f"  Department: {department}")
    print(f"  Classification: {classification}")
    print(f"  Status: queued")
    print(f"  Created: {now}")
    if deadline:
        print(f"  Deadline: {deadline}")
    if dependencies:
        print(f"  Dependencies: {dependencies}")
    
    return task_record


def task_status(task_id: str, db_path: Path = DB_PATH) -> dict | None:
    """Get the current status of a task from the central registry."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        print(f"Task {task_id} not found in registry.")
        return None
    
    columns = [
        "task_id", "original_task", "department", "classification", "status",
        "assigned_agent", "created_at", "started_at", "completed_at",
        "deadline", "dependencies", "dependents", "classification_data",
        "output_evidence", "verification_status", "verification_evidence",
        "cost_deduction", "note"
    ]
    
    task = dict(zip(columns, row))
    print(f"Task status for {task_id}:")
    print(f"  Department: {task['department']}")
    print(f"  Classification: {task['classification']}")
    print(f"  Status: {task['status']}")
    print(f"  Created: {task['created_at']}")
    if task['deadline']:
        print(f"  Deadline: {task['deadline']}")
    if task['verification_status'] != 'pending':
        print(f"  Verification: {task['verification_status']}")
    
    return task


def list_tasks(
    department: str | None = None,
    status: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """List tasks from the central registry, optionally filtered."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    query = "SELECT task_id, original_task, department, classification, status, created_at FROM tasks"
    params = []
    conditions = []
    
    if department:
        conditions.append("department = ?")
        params.append(department)
    if status:
        conditions.append("status = ?")
        params.append(status)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    columns = ["task_id", "original_task", "department", "classification", "status", "created_at"]
    return [dict(zip(columns, row)) for row in rows]


def main():
    """Main entry point for Phase 2 task registry."""
    print("=" * 60)
    print("PHASE 2 — Central Task Registry")
    print("=" * 60)
    print()
    
    # Initialize database
    db_path = init_db()
    print()
    
    # Example: Create a test task
    print("Creating test task...")
    task = create_task(
        original_task="Phase 2 test: dispatch research task for hypothesis validation",
        department="research",
        classification="ACTIONABLE",
        deadline=None,
        dependencies=None,
    )
    print()
    
    # Check task status
    print("Checking task status...")
    status = task_status(task["task_id"])
    print()
    
    # List all tasks
    print("All tasks in registry:")
    all_tasks = list_tasks()
    for t in all_tasks:
        print(f"  {t['task_id']}: {t['original_task'][:40]}... | {t['department']} | {t['status']} | {t['classification']}")
    print()
    
    print("=" * 60)
    print("Phase 2 complete. Task registry operational.")
    print("=" * 60)


if __name__ == "__main__":
    main()