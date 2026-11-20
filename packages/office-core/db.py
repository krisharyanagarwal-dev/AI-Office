#!/usr/bin/env python3
"""
office-core database module
SQLite task store + JSONL append-only log
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, List, Dict
from contextlib import contextmanager
import threading

DB_PATH = Path.home() / "AI-Office" / "packages" / "office-core" / "tasks.db"
LOG_PATH = Path.home() / "AI-Office" / "packages" / "office-core" / "tasks.log"
MIGRATIONS_DIR = Path.home() / "AI-Office" / "packages" / "office-core" / "migrations"

_local = threading.local()

def get_conn() -> sqlite3.Connection:
    """Get thread-local database connection."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys = ON")
        _local.conn.execute("PRAGMA journal_mode = WAL")
    return _local.conn

@contextmanager
def transaction():
    """Transaction context manager."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def init_db():
    """Initialize database with migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    
    # Run migrations in order
    for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        with open(migration_file) as f:
            sql = f.read()
        conn.executescript(sql)
    conn.commit()

def log_event(task_id: str, event_type: str, payload: Optional[Dict] = None):
    """Append event to JSONL log and database."""
    event = {
        "task_id": task_id,
        "event_type": event_type,
        "payload": payload or {},
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    # JSONL log (append-only, crash-safe)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")
    # Database
    with transaction() as conn:
        conn.execute(
            "INSERT INTO task_events (task_id, event_type, payload) VALUES (?, ?, ?)",
            (task_id, event_type, json.dumps(payload or {}))
        )

# --- Task operations ---

def create_task(
    id: str,
    title: str,
    description: str = "",
    status: str = "pending",
    priority: int = 0,
    assignee: Optional[str] = None,
    source: str = "cli",
    tags: str = "",
    depends_on: Optional[List[str]] = None,
    metadata: Optional[Dict] = None
) -> str:
    """Create a new task."""
    with transaction() as conn:
        conn.execute("""
            INSERT INTO tasks (id, title, description, status, priority, assignee, source, tags, depends_on, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            id, title, description, status, priority, assignee, source, tags,
            json.dumps(depends_on or []),
            json.dumps(metadata or {})
        ))
    log_event(id, "created", {"title": title, "source": source})
    return id

def get_task(id: str) -> Optional[Dict]:
    """Get task by ID."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (id,)).fetchone()
    if row:
        return dict(row)
    return None

def update_task(id: str, **kwargs) -> bool:
    """Update task fields."""
    allowed = {"title", "description", "status", "priority", "assignee", "tags", "depends_on", "metadata", "error"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    
    # Convert complex types to JSON
    if "depends_on" in updates and isinstance(updates["depends_on"], list):
        updates["depends_on"] = json.dumps(updates["depends_on"])
    if "metadata" in updates and isinstance(updates["metadata"], dict):
        updates["metadata"] = json.dumps(updates["metadata"])
    
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [id]
    
    with transaction() as conn:
        cursor = conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount > 0:
            log_event(id, "updated", updates)
            return True
    return False

def list_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "priority DESC, created_at ASC"
) -> List[Dict]:
    """List tasks with filters."""
    conn = get_conn()
    where = []
    params = []
    
    if status:
        where.append("status = ?")
        params.append(status)
    if assignee:
        where.append("assignee = ?")
        params.append(assignee)
    if source:
        where.append("source = ?")
        params.append(source)
    
    where_clause = "WHERE " + " AND ".join(where) if where else ""
    query = f"SELECT * FROM tasks {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]

def delete_task(id: str) -> bool:
    """Delete a task."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (id,))
        if cursor.rowcount > 0:
            log_event(id, "deleted", {})
            return True
    return False

# --- Agent operations ---

def upsert_agent(
    name: str,
    type: str,
    model: Optional[str] = None,
    tools: Optional[List[str]] = None,
    policy: Optional[Dict] = None,
    launchd_label: Optional[str] = None,
    health_endpoint: Optional[str] = None,
    schedule: Optional[str] = None,
    enabled: bool = True,
    metadata: Optional[Dict] = None
):
    """Insert or update agent."""
    with transaction() as conn:
        conn.execute("""
            INSERT INTO agents (name, type, model, tools, policy, launchd_label, health_endpoint, schedule, enabled, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                type=excluded.type,
                model=excluded.model,
                tools=excluded.tools,
                policy=excluded.policy,
                launchd_label=excluded.launchd_label,
                health_endpoint=excluded.health_endpoint,
                schedule=excluded.schedule,
                enabled=excluded.enabled,
                metadata=excluded.metadata,
                updated_at=CURRENT_TIMESTAMP
        """, (
            name, type, model,
            json.dumps(tools or []),
            json.dumps(policy or {}),
            launchd_label, health_endpoint, schedule,
            1 if enabled else 0,
            json.dumps(metadata or {})
        ))

def get_agent(name: str) -> Optional[Dict]:
    """Get agent by name."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None

def list_agents(enabled_only: bool = False) -> List[Dict]:
    """List all agents."""
    conn = get_conn()
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(f"SELECT * FROM agents {where} ORDER BY name").fetchall()
    return [dict(row) for row in rows]

def delete_agent(name: str) -> bool:
    """Delete agent."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM agents WHERE name = ?", (name,))
        return cursor.rowcount > 0

# --- Model router operations ---

def upsert_model_route(
    name: str,
    backend: str,
    endpoint: str,
    models: Optional[List[str]] = None,
    priority: int = 0,
    enabled: bool = True,
    config: Optional[Dict] = None
):
    """Insert or update model route."""
    with transaction() as conn:
        conn.execute("""
            INSERT INTO model_routes (name, backend, endpoint, models, priority, enabled, config)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                backend=excluded.backend,
                endpoint=excluded.endpoint,
                models=excluded.models,
                priority=excluded.priority,
                enabled=excluded.enabled,
                config=excluded.config,
                updated_at=CURRENT_TIMESTAMP
        """, (
            name, backend, endpoint,
            json.dumps(models or []),
            priority,
            1 if enabled else 0,
            json.dumps(config or {})
        ))

def get_model_route(name: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM model_routes WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None

def list_model_routes(enabled_only: bool = False) -> List[Dict]:
    conn = get_conn()
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(f"SELECT * FROM model_routes {where} ORDER BY priority DESC, name").fetchall()
    return [dict(row) for row in rows]

# --- Launchd job operations ---

def upsert_launchd_job(
    label: str,
    agent_name: str,
    program: List[str],
    working_directory: Optional[str] = None,
    environment: Optional[Dict] = None,
    run_at_load: bool = True,
    keep_alive: bool = True,
    throttle_interval: int = 30,
    start_calendar_interval: Optional[Dict] = None,
    standard_out_path: Optional[str] = None,
    standard_error_path: Optional[str] = None,
    process_type: str = "Background",
    enabled: bool = True
):
    """Insert or update launchd job."""
    with transaction() as conn:
        conn.execute("""
            INSERT INTO launchd_jobs (label, agent_name, program, working_directory, environment,
                run_at_load, keep_alive, throttle_interval, start_calendar_interval,
                standard_out_path, standard_error_path, process_type, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(label) DO UPDATE SET
                agent_name=excluded.agent_name,
                program=excluded.program,
                working_directory=excluded.working_directory,
                environment=excluded.environment,
                run_at_load=excluded.run_at_load,
                keep_alive=excluded.keep_alive,
                throttle_interval=excluded.throttle_interval,
                start_calendar_interval=excluded.start_calendar_interval,
                standard_out_path=excluded.standard_out_path,
                standard_error_path=excluded.standard_error_path,
                process_type=excluded.process_type,
                enabled=excluded.enabled,
                updated_at=CURRENT_TIMESTAMP
        """, (
            label, agent_name, json.dumps(program),
            working_directory,
            json.dumps(environment or {}),
            1 if run_at_load else 0,
            1 if keep_alive else 0,
            throttle_interval,
            json.dumps(start_calendar_interval) if start_calendar_interval else None,
            standard_out_path,
            standard_error_path,
            process_type,
            1 if enabled else 0
        ))

def get_launchd_job(label: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM launchd_jobs WHERE label = ?", (label,)).fetchone()
    return dict(row) if row else None

def list_launchd_jobs(enabled_only: bool = False) -> List[Dict]:
    conn = get_conn()
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(f"SELECT * FROM launchd_jobs {where} ORDER BY label").fetchall()
    return [dict(row) for row in rows]


def delete_model_route(name: str) -> bool:
    """Delete a model route."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM model_routes WHERE name = ?", (name,))
        return cursor.rowcount > 0


def delete_launchd_job(label: str) -> bool:
    """Delete a launchd job."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM launchd_jobs WHERE label = ?", (label,))
        return cursor.rowcount > 0

# --- System state ---

def set_state(key: str, value: Any):
    with transaction() as conn:
        conn.execute("""
            INSERT INTO system_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """, (key, json.dumps(value) if not isinstance(value, str) else value))

def get_state(key: str, default: Any = None) -> Any:
    conn = get_conn()
    row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return row[0]
    return default

# Initialize on import
init_db()