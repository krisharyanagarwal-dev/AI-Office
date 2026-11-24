# Task Queue and Inbox Architecture

**Based on**: Master System Prompt Section 5 (Autonomous Task Execution), Section 6 (Autonomous Office Lifecycle), Section 15 (Make the Office Real)  
**Generated**: 2026-11-23  
**Purpose**: Discovery audit — task queue and inbox architecture for unified AI Office

---

## Inbox Architecture: _office/inbox/

### 1. Inbox Item Structure

| Field | Format | Example | Status |
|---|---|---|---|
| `title` | Markdown heading text | `# alerting.md` | Present in all 60+ items |
| `content` | Free text | `"Angela: ..."` | Present |
| `category` | Derived from content | `alerting`, `arb-tracker`, etc. | Derivable from filename |
| `actionable` | Boolean | `true` (most items) | Needed: classification pipeline |
| `duplicate_of` | Task ID or `null` | `null` or `c-abc12345` | Not tracked |
| `status` | One of 6 values | `RESOLVED` or `INFORMATIONAL` | Per Section 2: INFORMATIONAL/ACTIONABLE/AWAITING APPROVAL/IN PROGRESS/RESOLVED/DUPLICATE/BLOCKED |
| `created_timestamp` | ISO format | `2026-11-19T17:30:00Z` | Not present in current items |
| `deadline` | ISO format or `null` | `null` | Not present |
| `assigned_department` | Department name or `null` | `null` | Not present |
| `task_id` | UUID format or `null` | `null` | Not present (per company_dispatcher.py: `c-<8hex>` per-dispatch) |

### 2. Current Inbox Item Analysis

**60+ items** in `_office/inbox/` (alerting.md → weekly-reviewer.md). Selected analysis:

| Filename | Category (inferred) | Actionable? | Notes |
|---|---|---|---|
| `alerting.md` | alerting | ✅ Yes | System alert |
| `arb-tracker.md` | arbitration tracking | ✅ Yes | Audit tracker |
| `architect.md` | architecture | ✅ Yes | System design |
| `auditor.md` | auditing | ✅ Yes | Quality audit |
| `backup-keeper.md` | backup | ✅ Yes | Data protection |
| `code-quality.md` | code quality | ✅ Yes | Code metrics |
| `cost-auditor.md` | cost | ✅ Yes | Financial audit |
| `dashboard-keeper.md` | dashboard | ✅ Yes | UI status |
| `disk-keeper.md` | disk | ✅ Yes | Storage monitoring |
| `dispatcher.md` | dispatch | ✅ Yes | Task routing |
| `docs-writer.md` | documentation | ✅ Yes | Doc generation |
| `eve.md` | entity | ✅ Yes | Subject reference |
| `f8.md` | f8 | ✅ Yes | System flag |
| `f9.md` | f9 | ✅ Yes | System flag |
| `forge.md` | forge | ✅ Yes | System operation |
| `funding-carry.md` | funding | ✅ Yes | Capital carry |
| `general.md` | general | ✅ Yes | General topic |
| `god.md` | governance | ✅ Yes | Authority figure |
| `jim.md` | person | ✅ Yes | Individual reference |
| `kevin.md` | person | ✅ Yes | Individual reference |
| `key-health.md` | key health | ✅ Yes | Security/access |
| `mainbot.md` | mainbot | ✅ Yes | Primary agent |
| `mcp-keeper.md` | MCP | ✅ Yes | MCP keeper |
| `oscar.md` | entity | ✅ Yes | Subject reference |
| `paper-trader.md` | trading | ✅ Yes | Trading activity |
| `performance.md` | performance | ✅ Yes | Metrics |
| `pm-attribution.md` | PM | ✅ Yes | Performance attribution |
| `pm-data.md` | PM data | ✅ Yes | PM metrics |
| `pm-ops.md` | PM ops | ✅ Yes | PM operations |
| `pm-risk.md` | PM risk | ✅ Yes | PM risk |
| `pm-signal.md` | PM signal | ✅ Yes | PM signal |
| `poly-bot-ops.md` | poly-bot | ✅ Yes | Bot operations |
| `rate-limit-tuner.md` | rate limit | ✅ Yes | Throttling config |
| `repo-keeper.md` | repository | ✅ Yes | Repo management |
| `research-digest.md` | research | ✅ Yes | Digest summary |
| `scalp-lab.md` | scalping | ✅ Yes | Scalping lab |
| `security.md` | security | ✅ Yes | Security audit |
| `sentinel.md` | sentinel | ✅ Yes | Monitoring sentinel |
| `specialist.md` | specialist | ✅ Yes | Expert reference |
| `svc-alphainsider.md` | service | ✅ Yes | Alpha insider |
| `svc-bridge.md` | service | ✅ Yes | Bridge service |
| `svc-entity.md` | service | ✅ Yes | Entity service |
| `svc-harness.md` | service | ✅ Yes | Harness service |
| `svc-jev.md` | service | ✅ Yes | JEV service |
| `svc-legs.md` | service | ✅ Yes | Legs service |
| `svc-marketdata.md` | market data | ✅ Yes | Market data feed |
| `svc-pubserver.md` | pubserver | ✅ Yes | Pub/sub server |
| `svc-quant.md` | quant | ✅ Yes | Quant service |
| `svc-repo.md` | repository | ✅ Yes | Repo service |
| `svc-taskops.md` | task ops | ✅ Yes | Task operations |
| `svc-watchdog.md` | watchdog | ✅ Yes | Watchdog monitor |
| `testing.md` | testing | ✅ Yes | Test suite |
| `toby.md` | person | ✅ Yes | Individual reference |
| `vault-librarian.md` | vault | ✅ Yes | Library vault |
| `venue-scout.md` | venue | ✅ Yes | Venue scouting |
| `weekly-reviewer.md` | weekly | ✅ Yes | Weekly review |

**All 60+ items are actionable (true)**. None are classified as INFORMATIONAL-only per the Section 2 classification system.

### 3. Inbox Classification Pipeline (Required)

Per Section 2 of master prompt, every incoming item must receive a classification:

```
INFORMATIONAL
  │
  ├──→ AWAITING APPROVAL
  │     │
  │     └──→ RESOLVED (after approval)
  │
  └──→ BLOCKED (cannot be processed)

ACTIONABLE
  │
  ├──→ IN PROGRESS (task assigned)
  │     │
  │     └──→ RESOLVED (task completed + verified)
  │
  └──→ DUPLICATE (same task already dispatched)
```

**Required Classification Fields** (not currently present):

| Field | Type | Description |
|---|---|---|
| `classification` | One of 6 (INFORMATIONAL, ACTIONABLE, AWAITING APPROVAL, IN PROGRESS, RESOLVED, DUPLICATE, BLOCKED) | Primary classification |
| `status` | One of 7 (the above + DUPLICATE) | Current task status |
| `priority` | Low/Medium/High/Urgent | Derived from content or manual assignment |
| `deadline` | ISO timestamp or null | When action must be completed by |
| `assigned_agent` | Agent ID or null | Who is responsible for execution |
| `task_id` | UUID or null | Central registry link |
| `duplicate_of` | Task ID or null | If DUPLICATE classification, which original task |
| `extracted_tasks` | Array of task descriptions | Actionable messages extracted from content |

### 4. Task Queue Architecture: `company.py` Dispatch

#### Current Dispatch Flow

```
Human → python company.py dispatch "task description" [--department X]
        │
        ▼
company.py cmd_dispatch()
        │
        ▼
subprocess.run([python, company_dispatcher.py, task])
        │
        ▼
company_dispatcher.py route_department(task)
        │
        ▼
score each department via keywords
return best department (or "assistant" if score == 0)
        │
        ▼
DEPARTMENT_HANDLERS[dept](task)
        │
        ▼
handler returns result dict with:
  - department
  - handled_by
  - task_id: f"c-{uuid.uuid4().hex[:8]}"
  - status: "queued"
  - note: department-specific description
  - available_commands (if applicable)
        │
        ▼
JSON result printed to console
```

#### Task Queue Gaps

| Gap | Current State | Required |
|---|---|---|
| No central task registry | Tasks exist only in JSON output (transient) | Create persistent task database (like `AI-Office/packages/office-core/tasks.db`) |
| No task status persistence | `queued` status lost after console output | Store status in database with timestamps |
| No dependency tracking | No dependencies between tasks | Add `depends_on` field to task records |
| No deadline assignment | No due dates | Add `deadline` field + deadline-aware routing |
| No cross-dispatch ID consistency | `c-<8hex>` generated per-invocation | Use full UUIDs or persistent ID scheme |
| No inbox → task pipeline | _office/inbox items not converted to tasks | Build inbox-to-task conversion script |
| No task completion verification | Agent says "complete" → assumed complete | Independent verification loop (Section 8: QA dept) |

#### Desired Task Queue Flow

```
Human / Inbox Item
    │
    ▼
Classification (INFORMATIONAL / ACTIONABLE / etc.)
    │
    ▼
Task Registry Lookup (by task_id or keyword)
    │
    ▼
Priority Assignment (based on age, category, department)
    │
    ▼
Agent Assignment (capability-aware, workload-balanced)
    │
    ▼
Dispatch with Persistent Task ID
    │
    ▼
Execution → Verification → Reporting → Improvement
```

### 5. Inbox-to-Task Conversion Pipeline (Required)

Per Section 15 of master prompt: "Start with a read-only discovery audit. Then begin implementing the highest-value safe improvements in isolated, testable stages."

**Phase 1 — Classification Script** (non-destructive test):

```python
#!/usr/bin/env python3
"""Classify _office inbox items per Section 2 of master prompt."""

import os
import re
from pathlib import Path

INBOX_DIR = Path("/Users/aryanagarwal/_office/inbox")
CLASSIFICATIONS = ["INFORMATIONAL", "ACTIONABLE", "AWAITING_APPROVAL",
                   "IN_PROGRESS", "RESOLVED", "DUPLICATE", "BLOCKED"]

def classify_item(filepath: Path) -> dict:
    """Classify a single inbox item based on its content."""
    content = filepath.read_text().lower()
    
    # Simple keyword-based classification
    if any(kw in content for kw in ["information", "inform", "just noting"]):
        classification = "INFORMATIONAL"
    elif any(kw in content for kw in ["task", "dispatch", "action", "do", "run"]):
        classification = "ACTIONABLE"
    else:
        classification = "INFORMATIONAL"  # default
    
    # Extract potential task descriptions
    tasks = re.findall(r'["\']([^"\']{10,})["\']', filepath.read_text())
    
    return {
        "filename": filepath.name,
        "classification": classification,
        "potential_tasks": tasks[:5],  # first 5 task mentions
        "content_preview": filepath.read_text()[:100] + "..." if len(filepath.read_text()) > 100 else filepath.read_text()
    }

def main():
    results = []
    for f in sorted(INBOX_DIR.glob("*.md")):
        results.append(classify_item(f))
    
    # Print summary
    counts = {c: 0 for c in CLASSIFICATIONS}
    for r in results:
        counts[r["classification"]] += 1
    
    print("Inbox Classification Summary:")
    for c, n in counts.items():
        print(f"  {c}: {n}")
    print(f"Total items: {len(results)}")

if __name__ == "__main__":
    main()
```

**Non-destructive test**: Run on current inbox items, verify classification counts make sense. No files modified.

**Phase 2 — Task Registry Integration** (after Phase 1 approval):

Add task ID generation + database storage to company_dispatcher.py, link inbox items to central task registry.

### 6. Task Lifecycle Per Section 5 (Autonomous Task Execution)

Per the master prompt Section 5, every task must follow:

```
STEP 1 — UNDERSTAND: Identify actual requested outcome
STEP 2 — PLAN: Break outcome into executable subtasks
STEP 3 — ASSIGN: Choose most suitable existing agent
STEP 4 — EXECUTE: Deliver work through supported mechanism
STEP 5 — MONITOR: Track progress, deadlines, failures
STEP 6 — VERIFY: Inspect actual result
STEP 7 — RECORD: Store decisions, outputs, evidence
STEP 8 — REPORT: Tell human what was accomplished, what remains, what needs approval
```

**Current State vs. Required**:

| Step | Current | Required (per Section 5) |
|---|---|---|
| 1 — Understand | ✅ Keyword routing understands intent | Add explicit outcome identification |
| 2 — Plan | ❌ Not formalized | Create plan per task, with subtasks |
| 3 — Assign | ✅ Routing to department | Add capability-aware agent selection |
| 4 — Execute | ✅ Department handlers run | Add monitoring + failure tracking |
| 5 — Monitor | ❌ No progress tracking | Add status persistence + deadline tracking |
| 6 — Verify | ❌ No independent verification | Build verification loop (Section 8: QA dept) |
| 7 — Record | ❌ Partial (logs only) | Store decisions + outputs + evidence with provenance |
| 8 — Report | ✅ Console JSON output | Centralized reporting dashboard + HUD integration |

### 7. Central Task Registry Design (Required)

| Field | Type | Description |
|---|---|---|
| `task_id` | UUIDv4 | Persistent unique identifier |
| `original_task` | Text | Human/inbox original description |
| `department` | Enum | research / trading / fleet / upgrade / ops / assistant |
| `classification` | Enum | INFORMATIONAL / ACTIONABLE / AWAITING APPROVAL / IN_PROGRESS / RESOLVED / DUPLICATE / BLOCKED |
| `status` | Enum | queued / in_progress / completed / failed / blocked |
| `assigned_agent` | String or null | Agent ID or handling entity |
| `created_at` | ISO timestamp | When task was created |
| `started_at` | ISO timestamp or null | When execution began |
| `completed_at` | ISO timestamp or null | When execution finished |
| `deadline` | ISO timestamp or null | When task must be completed |
| `dependencies` | Array of task_id | Tasks this depends on |
| `dependents` | Array of task_id | Tasks that depend on this one |
| `classification_data` | JSON | Additional classification fields (extracted tasks, priority, etc.) |
| `output_evidence` | JSON | Verification output, logs, metrics |
| `verification_status` | Enum | pending / verified / failed / inconclusive |
| `cost_deduction` | Float or null | Groww costs deducted (brokerage, STT, stamp, GST, slippage) per charter rule 2 |

### 8. Task Queue Metrics (Current State)

| Metric | Value | Source |
|---|---|---|
| Total inbox items | ~60 | `_office/inbox/` directory listing |
| Tasks dispatched today | Unknown | `logs/company.log` would have this |
| Successful dispatches | Unknown | No persistent tracking |
| Failed dispatches | Unknown | No tracking |
| Average dispatch latency | Unknown | No timing recorded |
| Tasks with deadlines | 0 | No deadline field in any system |
| Cross-department tasks | 0 | No dependency tracking |

---

## Task Queue and Inbox Architecture Summary

### What Works (Verified)
- `company.py dispatch` command functional
- `company_dispatcher.py` keyword routing to 6 departments
- 60+ inbox items in `_office/inbox/`
- JSON task output with `task_id`, `department`, `status`, `note`
- PNL ledger, metrics endpoint, stock analysis bot

### What's Missing (Gaps)
- **Inbox classification pipeline** (Section 2: every item must receive classification)
- **Central task registry** (no persistent task IDs across dispatches)
- **Task status tracking** (no status persistence beyond console output)
- **Dependency tracking** (no inter-task dependencies)
- **Deadline assignment** (no due dates anywhere in system)
- **Inbox → task pipeline** (no conversion from inbox items to dispatched tasks)
- **Independent verification** (Section 8: "A task is not complete merely because an agent says it is complete")
- **Reporting dashboard** (Section 8: "Report meaningful results, not fabricated healthy statuses")

### Priority Implementation Order

1. **P0**: Inbox classification pipeline (classify all 60+ items per Section 2)
2. **P1**: Central task registry with persistent UUIDs + status tracking
3. **P2**: Inbox → task conversion script (classify + create task records)
4. **P3**: Verification loop (Section 8: independent second-model verification)
5. **P4**: Reporting dashboard (Section 8: cross-department operational knowledge)
6. **P5**: Priority escalation + deadline-aware routing

---

*End of Task Queue and Inbox Architecture*