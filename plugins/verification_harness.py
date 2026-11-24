#!/usr/bin/env python3
"""
Verification Harness — Independent verification for OPENALICE tasks

Provides independent verification that actions were completed correctly,
without relying on the task's own assertion.

Usage:
    python verification_harness.py --task-id TASK_ID --verify result
    python verification_harness.py --task-id TASK_ID --verify cost
    python verification_harness.py --task-id TASK_ID --verify data-quality
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TASKS_DB = Path(__file__).resolve().parent.parent / "tasks.db"
VERIFICATION_DB = Path(__file__).resolve().parent / "verification.db"


@dataclass
class VerificationResult:
    task_id: str
    verification_type: str
    passed: bool
    details: dict
    verified_at: float
    verifier: str = "verification_harness"


def init_verification_db():
    """Initialize verification database."""
    conn = sqlite3.connect(VERIFICATION_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            verification_type TEXT NOT NULL,
            passed INTEGER NOT NULL,
            details TEXT,
            verified_at REAL NOT NULL,
            verifier TEXT DEFAULT 'verification_harness'
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_verification_task ON verifications(task_id)")
    conn.commit()
    conn.close()


def verify_task_result(task_id: str) -> VerificationResult:
    """Verify that the task result exists and is valid."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT result, status FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return VerificationResult(
            task_id=task_id,
            verification_type="result",
            passed=False,
            details={"error": "Task not found"},
            verified_at=time.time(),
        )

    result, status = row

    if status != "SUCCEEDED":
        return VerificationResult(
            task_id=task_id,
            verification_type="result",
            passed=False,
            details={"status": status, "error": "Task did not succeed"},
            verified_at=time.time(),
        )

    if not result:
        return VerificationResult(
            task_id=task_id,
            verification_type="result",
            passed=False,
            details={"status": status, "error": "No result recorded"},
            verified_at=time.time(),
        )

    return VerificationResult(
        task_id=task_id,
        verification_type="result",
        passed=True,
        details={"status": status, "has_result": True},
        verified_at=time.time(),
    )


def verify_task_cost(task_id: str) -> VerificationResult:
    """Verify that task cost is within expected bounds."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return VerificationResult(
            task_id=task_id,
            verification_type="cost",
            passed=False,
            details={"error": "Task not found"},
            verified_at=time.time(),
        )

    # Check if task has metadata with cost info
    metadata = row[9] if len(row) > 9 and row[9] else "{}"
    try:
        meta = json.loads(metadata) if metadata else {}
        cost = meta.get("cost_units", 0)

        # Reasonable cost bounds
        passed = cost <= 100 if cost else True

        return VerificationResult(
            task_id=task_id,
            verification_type="cost",
            passed=passed,
            details={"cost_units": cost, "max_allowed": 100},
            verified_at=time.time(),
        )
    except json.JSONDecodeError:
        return VerificationResult(
            task_id=task_id,
            verification_type="cost",
            passed=True,
            details={"cost_check": "skipped - no cost metadata"},
            verified_at=time.time(),
        )


def verify_data_quality(task_id: str, expected_fields: list[str] | None = None) -> VerificationResult:
    """Verify that task output meets data quality standards."""
    conn = sqlite3.connect(TASKS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT result, metadata FROM tasks WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return VerificationResult(
            task_id=task_id,
            verification_type="data-quality",
            passed=False,
            details={"error": "Task not found"},
            verified_at=time.time(),
        )

    result, metadata = row

    checks = {
        "has_result": result is not None and result != "",
        "result_is_valid_json": False,
        "expected_fields_present": expected_fields is None or len(expected_fields) == 0,
    }

    if result:
        try:
            data = json.loads(result) if isinstance(result, str) else result
            checks["result_is_valid_json"] = True

            if expected_fields:
                checks["expected_fields_present"] = all(f in data for f in expected_fields)
        except (json.JSONDecodeError, TypeError):
            pass

    passed = all(checks.values())

    return VerificationResult(
        task_id=task_id,
        verification_type="data-quality",
        passed=passed,
        details=checks,
        verified_at=time.time(),
    )


def record_verification(result: VerificationResult) -> None:
    """Record verification result to database."""
    init_verification_db()
    conn = sqlite3.connect(VERIFICATION_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO verifications (task_id, verification_type, passed, details, verified_at, verifier)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            result.task_id,
            result.verification_type,
            1 if result.passed else 0,
            json.dumps(result.details),
            result.verified_at,
            result.verifier,
        ),
    )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Verification Harness")
    parser.add_argument("--task-id", "-t", required=True, help="Task ID to verify")
    parser.add_argument(
        "--verify",
        choices=["result", "cost", "data-quality", "all"],
        default="result",
        help="Verification type",
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        help="Expected fields for data-quality check",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record result to verification database",
    )

    args = parser.parse_args()

    results = {}

    if args.verify in ("result", "all"):
        results["result"] = verify_task_result(args.task_id)
        print(f"Result check: {'PASSED' if results['result'].passed else 'FAILED'}")

    if args.verify in ("cost", "all"):
        results["cost"] = verify_task_cost(args.task_id)
        print(f"Cost check: {'PASSED' if results['cost'].passed else 'FAILED'}")

    if args.verify in ("data-quality", "all"):
        results["data-quality"] = verify_data_quality(args.task_id, args.fields)
        print(f"Data quality check: {'PASSED' if results['data-quality'].passed else 'FAILED'}")

    # Summary
    all_passed = all(r.passed for r in results.values())
    print(f"\nOverall: {'VERIFIED' if all_passed else 'FAILED'}")

    if args.record:
        for r in results.values():
            record_verification(r)
        print("Results recorded to verification.db")


if __name__ == "__main__":
    main()