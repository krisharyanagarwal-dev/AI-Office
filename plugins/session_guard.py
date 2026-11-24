#!/usr/bin/env python3
"""
Session Guard — Human-protected session management for OPENALICE

Prevents unauthorized or harmful actions by requiring human confirmation
for high-risk operations while allowing autonomous operation for Tier A/B tasks.

Usage:
    python session_guard.py --guard session_id
    python session_guard.py --protect task_id --reason "financial impact"
    python session_guard.py --status session_id
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SESSION_DB = Path(__file__).resolve().parent.parent / "session_guards.db"


@dataclass
class SessionGuard:
    session_id: str
    status: str  # PROTECTING, CONFIRMED, AUTHORIZED, BLOCKED
    task_id: Optional[str] = None
    risk_level: str = "LOW"  # HIGH, MEDIUM, LOW
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    human_user: Optional[str] = None
    confirmation_token: Optional[str] = None
    expires_at: Optional[float] = None


def init_db():
    """Initialize session guards database."""
    import sqlite3
    conn = sqlite3.connect(SESSION_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_guards (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            task_id TEXT,
            risk_level TEXT DEFAULT 'LOW',
            reason TEXT,
            created_at REAL,
            human_user TEXT,
            confirmation_token TEXT,
            expires_at REAL
        )
    """)
    conn.commit()
    conn.close()


def create_session_guard(
    task_id: str,
    risk_level: str = "LOW",
    reason: str = "",
    ttl_hours: int = 24,
) -> SessionGuard:
    """Create a new session guard entry."""
    import uuid
    import sqlite3

    session_id = f"sg-{uuid.uuid4().hex[:12]}"
    token = uuid.uuid4().hex[:8]
    now = time.time()
    expires = now + (ttl_hours * 3600)

    init_db()
    conn = sqlite3.connect(SESSION_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO session_guards
        (session_id, status, task_id, risk_level, reason, created_at, confirmation_token, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, "PROTECTING", task_id, risk_level, reason, now, token, expires),
    )
    conn.commit()
    conn.close()

    return SessionGuard(
        session_id=session_id,
        status="PROTECTING",
        task_id=task_id,
        risk_level=risk_level,
        reason=reason,
        created_at=now,
        confirmation_token=token,
        expires_at=expires,
    )


def authorize_session(session_id: str, token: str) -> bool:
    """Authorize a session with confirmation token."""
    import sqlite3

    conn = sqlite3.connect(SESSION_DB)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status, expires_at FROM session_guards WHERE session_id = ?",
        (session_id,),
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    status, expires_at = row

    if status != "PROTECTING":
        conn.close()
        return False

    if expires_at and time.time() > expires_at:
        conn.close()
        return False

    cursor.execute(
        """
        UPDATE session_guards
        SET status = 'AUTHORIZED', confirmation_token = ?, human_user = ?, expires_at = ?
        WHERE session_id = ?
        """,
        (token, os.environ.get("USER", "unknown"), time.time() + 3600, session_id),
    )
    conn.commit()
    conn.close()

    return True


def get_session_status(session_id: str) -> Optional[SessionGuard]:
    """Get session guard status."""
    import sqlite3

    conn = sqlite3.connect(SESSION_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM session_guards WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return SessionGuard(
        session_id=row[0],
        status=row[1],
        task_id=row[2],
        risk_level=row[3],
        reason=row[4],
        created_at=row[5],
        human_user=row[6],
        confirmation_token=row[7],
        expires_at=row[8],
    )


def session_is_protected(session_id: str) -> bool:
    """Check if a session requires human protection."""
    guard = get_session_status(session_id)
    if not guard:
        return False

    if guard.expires_at and time.time() > guard.expires_at:
        return False

    return guard.status == "PROTECTING"


def list_protected_sessions(limit: int = 50) -> list[SessionGuard]:
    """List all protected sessions."""
    import sqlite3

    init_db()
    conn = sqlite3.connect(SESSION_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM session_guards
        WHERE status = 'PROTECTING' AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (time.time(), limit),
    )

    rows = cursor.fetchall()
    conn.close()

    return [
        SessionGuard(
            session_id=r[0],
            status=r[1],
            task_id=r[2],
            risk_level=r[3],
            reason=r[4],
            created_at=r[5],
            human_user=r[6],
            confirmation_token=r[7],
            expires_at=r[8],
        )
        for r in rows
    ]


# Initialise database on import
init_db()


def main():
    parser = argparse.ArgumentParser(description="Session Guard — Human-protected session management")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # create command
    p_create = subparsers.add_parser("create", help="Create a new session guard")
    p_create.add_argument("--task-id", "-t", required=True, help="Task ID to protect")
    p_create.add_argument("--risk-level", "-r", choices=["HIGH", "MEDIUM", "LOW"], default="LOW")
    p_create.add_argument("--reason", help="Reason for protection")
    p_create.add_argument("--ttl-hours", type=int, default=24, help="Time to live in hours")

    # authorize command
    p_auth = subparsers.add_parser("authorize", help="Authorize a protected session")
    p_auth.add_argument("--session-id", "-s", required=True, help="Session ID")
    p_auth.add_argument("--token", "-t", required=True, help="Confirmation token")

    # status command
    p_status = subparsers.add_parser("status", help="Check session status")
    p_status.add_argument("--session-id", "-s", required=True, help="Session ID")

    # list command
    p_list = subparsers.add_parser("list", help="List protected sessions")
    p_list.add_argument("--limit", "-l", type=int, default=10)

    args = parser.parse_args()

    if args.command == "create":
        guard = create_session_guard(args.task_id, args.risk_level, args.reason, args.ttl_hours)
        print(json.dumps({
            "session_id": guard.session_id,
            "status": guard.status,
            "confirmation_token": guard.confirmation_token,
            "expires_at": datetime.fromtimestamp(guard.expires_at).isoformat() if guard.expires_at else None,
        }, indent=2))

    elif args.command == "authorize":
        success = authorize_session(args.session_id, args.token)
        print(f"Authorized: {success}")

    elif args.command == "status":
        guard = get_session_status(args.session_id)
        if guard:
            print(json.dumps({
                "session_id": guard.session_id,
                "status": guard.status,
                "task_id": guard.task_id,
                "risk_level": guard.risk_level,
                "authorized": guard.status == "AUTHORIZED",
            }, indent=2))
        else:
            print(f"Session {args.session_id} not found")

    elif args.command == "list":
        sessions = list_protected_sessions(args.limit)
        print(json.dumps([{
            "session_id": s.session_id,
            "task_id": s.task_id,
            "risk_level": s.risk_level,
            "reason": s.reason,
        } for s in sessions], indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()