#!/usr/bin/env python3
"""
Task Registry — SQLite-backed task database for OPENALICE
Implements the task lifecycle: SUBMITTED → VALIDATING → QUEUED → LEASED → RUNNING → VERIFYING → SUCCEEDED → FAILED

Used by company_dispatcher.py for persistent task tracking.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TASKS_DB = Path(__file__).parent / "tasks.db"

TASK_STATES = [
    "SUBMITTED",
    "VALIDATING",
    "QUEUED",
    "LEASED",
    "RUNNING",
    "VERIFYING",
    "SUCCEEDED",
    "FAILED",
]


@dataclass
class Task:
    task_id: str
    description: str
    department: str
    status: str
    created_at: float
    updated_at: float
    assigned_agent: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None


def init_db() -> None:
    """Initialize the tasks database."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            department TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SUBMITTED',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            assigned_agent TEXT,
            result TEXT,
            error TEXT,
            priority INTEGER DEFAULT 0,
            metadata TEXT
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_department ON tasks(department)")

    conn.commit()
    conn.close()


def create_task(description: str, department: str, priority: int = 0, metadata: Optional[dict] = None) -> Task:
    """Create a new task in SUBMITTED state."""
    now = time.time()
    task_id = f"t-{uuid.uuid4().hex[:12]}"

    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO tasks (task_id, description, department, status, created_at, updated_at, priority, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            description,
            department,
            "SUBMITTED",
            now,
            now,
            priority,
            str(metadata) if metadata else None,
        ),
    )

    conn.commit()
    conn.close()

    return Task(
        task_id=task_id,
        description=description,
        department=department,
        status="SUBMITTED",
        created_at=now,
        updated_at=now,
    )


def update_status(task_id: str, status: str, error: Optional[str] = None) -> bool:
    """Update task status. Returns True if task exists."""
    now = time.time()

    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE tasks SET status = ?, updated_at = ?, error = ?
        WHERE task_id = ?
        """,
        (status, now, error, task_id),
    )

    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return changed


def assign_task(task_id: str, agent: str) -> bool:
    """Assign a task to an agent."""
    return update_status(task_id, "LEASED", agent=agent)


def set_result(task_id: str, result: str, status: str = "SUCCEEDED") -> bool:
    """Set task result and update status."""
    now = time.time()

    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE tasks SET status = ?, result = ?, updated_at = ?
        WHERE task_id = ?
        """,
        (status, result, now, task_id),
    )

    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return changed


def get_task(task_id: str) -> Optional[Task]:
    """Get a task by ID."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return Task(
        task_id=row[0],
        description=row[1],
        department=row[2],
        status=row[3],
        created_at=row[4],
        updated_at=row[5],
        assigned_agent=row[6],
        result=row[7],
        error=row[8],
    )


def queue_tasks(department: str, limit: int = 10) -> list[Task]:
    """Get tasks in QUEUED state for a department."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM tasks
        WHERE status = 'QUEUED' AND department = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (department, limit),
    )

    rows = cursor.fetchall()
    conn.close()

    tasks = []
    for row in rows:
        tasks.append(
            Task(
                task_id=row[0],
                description=row[1],
                department=row[2],
                status=row[3],
                created_at=row[4],
                updated_at=row[5],
                assigned_agent=row[6],
                result=row[7],
                error=row[8],
            )
        )

    return tasks


def list_tasks(status: Optional[str] = None, department: Optional[str] = None, limit: int = 50) -> list[Task]:
    """List tasks filtered by status and/or department."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()

    query = "SELECT * FROM tasks"
    filters = []
    params = []

    if status:
        filters.append("status = ?")
        params.append(status)
    if department:
        filters.append("department = ?")
        params.append(department)

    if filters:
        query += " WHERE " + " AND ".join(filters)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [
        Task(
            task_id=row[0],
            description=row[1],
            department=row[2],
            status=row[3],
            created_at=row[4],
            updated_at=row[5],
            assigned_agent=row[6],
            result=row[7],
            error=row[8],
        )
        for row in rows
    ]


# Initialise database on import
init_db()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Task Registry")
    parser.add_argument("action", choices=["create", "list", "queue", "status", "assign", "result"])
    parser.add_argument("--department", "-d", help="Department")
    parser.add_argument("--description", help="Task description")
    parser.add_argument("--task-id", "-t", help="Task ID")
    parser.add_argument("--agent", "-a", help="Agent to assign")
    parser.add_argument("--status", "-s", help="Status")
    parser.add_argument("--result", "-r", help="Result")
    parser.add_argument("--limit", "-l", type=int, default=10)

    args = parser.parse_args()

    if args.action == "create":
        if not args.description:
            print("ERROR: --description required for create")
            exit(1)
        task = create_task(args.description, args.department or "assistant")
        print(json.dumps({
            "task_id": task.task_id,
            "status": task.status,
            "department": task.department,
        }, indent=2))

    elif args.action == "list":
        tasks = list_tasks(args.status, args.department, args.limit)
        print(json.dumps([{
            "task_id": t.task_id,
            "status": t.status,
            "department": t.department,
            "description": t.description[:60] + "..." if len(t.description) > 60 else t.description,
        } for t in tasks], indent=2))

    elif args.action == "queue":
        tasks = queue_tasks(args.department or "assistant", args.limit)
        print(json.dumps([{
            "task_id": t.task_id,
            "status": t.status,
            "department": t.department,
        } for t in tasks], indent=2))

    elif args.action == "status":
        if not args.task_id:
            print("ERROR: --task-id required")
            exit(1)
        task = get_task(args.task_id)
        if task:
            print(json.dumps({
                "task_id": task.task_id,
                "status": task.status,
                "assigned_agent": task.assigned_agent,
            }, indent=2))
        else:
            print(f"Task {args.task_id} not found")

    elif args.action == "assign":
        if not args.task_id or not args.agent:
            print("ERROR: --task-id and --agent required")
            exit(1)
        success = assign_task(args.task_id, args.agent)
        print(f"Assigned: {success}")

    elif args.action == "result":
        if not args.task_id:
            print("ERROR: --task-id required")
            exit(1)
        set_result(args.task_id, args.result or "", args.status or "SUCCEEDED")
        print(f"Result set for {args.task_id}")