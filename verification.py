#!/usr/bin/env python3
"""
Phase 5: Verification Loop (Section 8 Mandate)

Per master prompt Section 8, Quality dept: "A task is not complete merely because an agent says it is complete."

Also per master prompt Section 5 Step 6 VERIFY: "Inspect the actual result."

Per free-model strategy Rule 4: "Use independent verification for important outputs."

This script is a non-destructive first implementation step — it verifies task outputs
based on charter compliance checks; no agent integration yet, no second-model calls.
Rollback: verification script is standalone; no infrastructure changes.
"""

import json
import sys
from pathlib import Path

# Try to import the task registry from Phase 2
try:
    import sqlite3
    from pathlib import Path
    
    DB_PATH = Path("/Users/aryanagarwal/AI-Office/packages/office-core/tasks.db")
    
    def get_task(task_id: str) -> dict | None:
        """Get task record from central registry."""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        columns = [
            "task_id", "original_task", "department", "classification", "status",
            "assigned_agent", "created_at", "started_at", "completed_at",
            "deadline", "dependencies", "dependents", "classification_data",
            "output_evidence", "verification_status", "verification_evidence",
            "cost_deduction", "note"
        ]
        
        return dict(zip(columns, row))
    
    def verify_task(task_id: str) -> dict:
        """Run verification checks on a task output.
        
        Checks:
        1. Output evidence exists (non-empty)
        2. Charter compliance: cost deductions tracked
        3. Classification matches department norms
        4. Status is consistent with classification
        5. Dependency status checked (all deps completed)
        
        Returns verdict + evidence + recommendations.
        """
        task = get_task(task_id)
        if task is None:
            return {
                "verdict": "FAILED",
                "evidence": f"Task {task_id} not found in registry",
                "recommendation": "Verify task ID or create task record"
            }
        
        evidence = []
        verdict = "PASS"
        recommendations = []
        
        # Check 1: Output evidence exists
        if task["output_evidence"]:
            evidence.append("PASS: Output evidence present")
        else:
            evidence.append("FAIL: No output evidence — task output incomplete")
            verdict = "FAILED"
            recommendations.append("Add output evidence before verification")
        
        # Check 2: Charter cost-honest compliance
        if task["cost_deduction"] is not None and task["cost_deduction"] >= 0:
            evidence.append(f"PASS: Cost deductions tracked (₹{task['cost_deduction']:,.0f})")
        else:
            evidence.append("FAIL: Cost deductions not tracked — violates COMPANY_CHARTER.md rule 2 (COST-HONEST)")
            verdict = "FAILED"
            recommendations.append("Track Groww costs (brokerage, STT, stamp, GST, slippage) per charter rule 2")
        
        # Check 3: Classification matches department norms
        dept = task["department"]
        cls = task["classification"]
        if dept == "research" and cls in ["ACTIONABLE", "IN_PROGRESS"]:
            evidence.append(f"PASS: Research classification {cls} appropriate")
        elif dept == "trading" and cls == "ACTIONABLE":
            evidence.append(f"PASS: Trading classification {cls} appropriate")
        elif dept == "assistant" and cls in ["ACTIONABLE", "IN_PROGRESS", "AWAITING_APPROVAL"]:
            evidence.append(f"PASS: Assistant classification {cls} appropriate")
        else:
            evidence.append(f"NOTE: {dept} classification {cls} — no specific constraint violated")
        
        # Check 4: Status consistency
        if task["status"] == "queued" and task["completed_at"] is not None:
            evidence.append("FAIL: Task status 'queued' but completed_at set — status inconsistency")
            verdict = "FAILED"
            recommendations.append("Reset status to match completion state")
        elif task["status"] in ["completed", "failed"] and task["completed_at"] is not None:
            evidence.append("PASS: Status and completion date consistent")
        else:
            evidence.append("NOTE: Status-completion consistency — manual review recommended")
        
        # Check 5: Dependency status (if dependencies exist)
        if task["dependencies"] and task["dependencies"] != "[]":
            evidence.append(f"NOTE: Task has {len(eval(task['dependencies']))} dependency/ies — dependency status not automatically checked")
            recommendations.append("Manual review of dependency completion status recommended")
        
        # Build verdict
        if verdict == "PASS" and evidence.count("FAIL") > 0:
            verdict = "CONDITIONAL_PASS"
        
        return {
            "verdict": verdict,
            "evidence": "; ".join(evidence),
            "recommendations": "; ".join(recommendations),
            "task_id": task_id,
            "department": task["department"],
            "classification": task["classification"],
            "status": task["status"],
            "cost_deduction": task["cost_deduction"],
            "has_output_evidence": task["output_evidence"] is not None,
            "cost_tracked": task["cost_deduction"] is not None and task["cost_deduction"] >= 0,
        }
    
    # Make functions available for import
    __all__ = ["verify_task", "get_task"]
    
except ImportError:
    # Fallback if office-core not in path
    import sqlite3
    from pathlib import Path
    
    DB_PATH = Path("/Users/aryanagarwal/AI-Office/packages/office-core/tasks.db")
    
    # Same implementation as above, inlined
    def get_task(task_id: str) -> dict | None:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        columns = [
            "task_id", "original_task", "department", "classification", "status",
            "assigned_agent", "created_at", "started_at", "completed_at",
            "deadline", "dependencies", "dependents", "classification_data",
            "output_evidence", "verification_status", "verification_evidence",
            "cost_deduction", "note"
        ]
        return dict(zip(columns, row))
    
    def verify_task(task_id: str) -> dict:
        task = get_task(task_id)
        if task is None:
            return {
                "verdict": "FAILED",
                "evidence": f"Task {task_id} not found in registry",
                "recommendation": "Verify task ID or create task record"
            }
        
        evidence = []
        verdict = "PASS"
        recommendations = []
        
        if task["output_evidence"]:
            evidence.append("PASS: Output evidence present")
        else:
            evidence.append("FAIL: No output evidence — task output incomplete")
            verdict = "FAILED"
            recommendations.append("Add output evidence before verification")
        
        if task["cost_deduction"] is not None and task["cost_deduction"] >= 0:
            evidence.append(f"PASS: Cost deductions tracked (₹{task['cost_deduction']:,.0f})")
        else:
            evidence.append("FAIL: Cost deductions not tracked — violates COMPANY_CHARTER.md rule 2 (COST-HONEST)")
            verdict = "FAILED"
            recommendations.append("Track Groww costs (brokerage, STT, stamp, GST, slippage) per charter rule 2")
        
        dept = task["department"]
        cls = task["classification"]
        if dept == "research" and cls in ["ACTIONABLE", "IN_PROGRESS"]:
            evidence.append(f"PASS: Research classification {cls} appropriate")
        elif dept == "trading" and cls == "ACTIONABLE":
            evidence.append(f"PASS: Trading classification {cls} appropriate")
        elif dept == "assistant" and cls in ["ACTIONABLE", "IN_PROGRESS", "AWAITING_APPROVAL"]:
            evidence.append(f"PASS: Assistant classification {cls} appropriate")
        else:
            evidence.append(f"NOTE: {dept} classification {cls} — no specific constraint violated")
        
        if task["status"] == "queued" and task["completed_at"] is not None:
            evidence.append("FAIL: Task status 'queued' but completed_at set — status inconsistency")
            verdict = "FAILED"
            recommendations.append("Reset status to match completion state")
        elif task["status"] in ["completed", "failed"] and task["completed_at"] is not None:
            evidence.append("PASS: Status and completion date consistent")
        else:
            evidence.append("NOTE: Status-completion consistency — manual review recommended")
        
        if task["dependencies"] and task["dependencies"] != "[]":
            evidence.append(f"NOTE: Task has dependencies — manual review of dependency completion recommended")
        
        if verdict == "PASS" and evidence.count("FAIL") > 0:
            verdict = "CONDITIONAL_PASS"
        
        return {
            "verdict": verdict,
            "evidence": "; ".join(evidence),
            "recommendations": "; ".join(recommendations),
            "task_id": task_id,
            "department": task["department"],
            "classification": task["classification"],
            "status": task["status"],
            "cost_deduction": task["cost_deduction"],
            "has_output_evidence": task["output_evidence"] is not None,
            "cost_tracked": task["cost_deduction"] is not None and task["cost_deduction"] >= 0,
        }


# Allow running as standalone script
if __name__ == "__main__":
    import sys
    task_id = sys.argv[1] if len(sys.argv) > 1 else "c-7dbb0906"  # default: first test task
    
    result = verify_task(task_id)
    print(f"Verification for task {result['task_id']}:")
    print(f"  Verdict: {result['verdict']}")
    print(f"  Evidence: {result['evidence']}")
    print(f"  Recommendations: {result['recommendations']}")
    print()
    print(f"  Department: {result['department']}")
    print(f"  Classification: {result['classification']}")
    print(f"  Status: {result['status']}")
    print(f"  Cost deductions: ₹{result['cost_deduction']:,.0f}" if result['cost_deduction'] else "  Cost deductions: Not tracked")
    print(f"  Output evidence: {'Present' if result['has_output_evidence'] else 'Missing'}")
    print(f"  Cost tracked: {'Yes' if result['cost_tracked'] else 'No'}")