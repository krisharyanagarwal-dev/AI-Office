# Prioritized Implementation Plan

**Based on**: Master System Prompt Section 15 (Make the Office Real) — "Then begin implementing the highest-value safe improvements in isolated, testable stages."  
**Generated**: 2026-11-23  
**Purpose**: Final of 11 deliverables — prioritized implementation plan for unified AI Office

---

## Implementation Philosophy (per Section 15)

> "Do not wait for another prompt to perform work that is already authorized.
> Do not ask the human to approve routine, reversible work.
> Stop and request authorization only for actions outside your permissions."

> "First milestone should be proving that one instruction can enter the office, reach an existing agent, produce a real deliverable, pass independent verification and appear as completed in the HUD."

### Key Principles

1. **Execution over discussion** — Implement in isolated, testable stages; no endless planning
2. **Evidence over assumptions** — Every claim must be verified; no proxy signals
3. **Reuse over rebuilding** — Enhance existing infrastructure; do not recreate working components
4. **Autonomy over unnecessary human prompting** — Automate reversible, low-risk work
5. **Verification over agent claims** — Independent verification; never claim feature operational without testing
6. **Shared visibility over isolated information** — All operational data visible in HUD, not siloed
7. **Reliability over raw agent count** — Fewer reliably working agents > more marginally working ones
8. **Efficiency over unnecessary model expenditure** — Free models first; local first; avoid expensive calls on simple work
9. **Safety over reckless automation** — Per charter: PAPER ONLY, kill switch LOCKED, no live orders
10. **Completed outcomes over generated plans** — Real deliverables > impressive plans

---

## Implementation Phases (Isolated, Testable Stages)

### Phase 1 — Inbox Classification Pipeline (P0, Medium Effort)

**Goal**: Classify _office/inbox items per Section 2 of master prompt  
**Success Criteria**: 5 sample items classified; classifications make sense per INFORMATIONAL/ACTIONABLE/AWAITING APPROVAL/IN PROGRESS/RESOLVED/DUPLICATE/BLOCKED  
**Test**: Run classification script on 5 inbox items; human reviews + approves  
**Rollback**: Classification script is standalone; no infrastructure changes; delete generated artifacts  
**Charter Compliance**: Paper-only, no live orders — classification is text-only, fully compliant  
**Dependencies**: None (enhances existing _office/inbox structure)  

**Implementation Steps**:
1. Create `classify_inbox.py` script (see free-integrations.md Phase 1 design)
2. Run on 5 sample inbox items (alerting.md, arb-tracker.md, dispatcher.md, key-health.md, weekly-reviewer.md)
3. Output classifications to console + write to `classified-inbox-items.json`
4. Human reviews classifications; approve or request adjustments
5. Once approved, integrate classification output into task registry (Phase 2)

**Non-Destructive Test Command**:
```bash
python classify_inbox.py --sample 5
```

---

### Phase 2 — Central Task Registry (P1, High Effort)

**Goal**: Create persistent task database with UUIDs, status tracking, deadlines, dependencies  
**Success Criteria**: Task record persists across company.py dispatch calls; task_id retrievable; status field observable  
**Test**: `python company.py dispatch "test task" --department research` → verify task_id retrievable from DB  
**Rollback**: Drop/recreate SQLite DB; original `company_dispatcher.py` keyword routing unchanged  
**Charter Compliance**: Fully compliant — adds persistence, no charter violations  
**Dependencies**: Phase 1 (classification pipeline) optional but recommended  

**Implementation Steps**:
1. Create `tasks.db` SQLite database with schema (task_id, original_task, department, classification, status, deadline, dependencies, created_at, started_at, completed_at, output_evidence, verification_status, cost_deduction)
2. Modify `company_dispatcher.py dispatch()` to write task record to DB on dispatch
3. Add `company.py task-status` command to query task DB
4. Add `company.py task-list` command to list all tasks
5. Non-destructive test: Dispatch task, verify DB record, verify retrieval

**Non-Destructive Test Command**:
```bash
python company.py dispatch "Phase 2 test task" --department research
python company.py task-status c-abc12345
```

---

### Phase 3 — Model Router Integration (P2, Medium Effort)

**Goal**: Integrate free-model inventory into task routing — select model per task based on allocation table  
**Success Criteria**: Task dispatch result includes model selection; free models preferred per allocation table; cost deductions tracked  
**Test**: `python company.py dispatch "research hypothesis about X" --department research` → model selection appears in output  
**Rollback**: Remove model router code; original keyword routing restored; no DB schema changes needed (optional extension)  
**Charter Compliance**: Paper-only + cost-honest — model router must deduct costs per charter rule 2; prefer free local models per Section 4 Rules 1+2  
**Dependencies**: Phase 1 optional; Phase 2 task registry helpful  

**Implementation Steps**:
1. Create `model_router.py` with `route_model(task_description, available_models)` function
2. Model router uses allocation table (from free-model-inventory.md) to select model class
3. Preferred order: local Ollama models → free API models → paid API models (all cost-deducted)
4. Integrate into `company_dispatcher.py` dispatch result (add `model_selected` field)
5. Add cost deduction logging per charter rule 2
6. Non-destructive test: Dispatch research task, verify model selection + cost log

**Non-Destructive Test Command**:
```bash
python company.py dispatch "research backtest of momentum strategy" --department research
```

---

### Phase 4 — Human-Protected Session Guard (P0, High Effort — Critical/Charter)

**Goal**: Implement session protection logic per COMPANY_CHARTER.md rule 5  
**Success Criteria**: Human-protected sessions identified + not eligible for automated kill/dispatch; HUD displays protected count with warning  
**Test**: Attempt dispatch on task that would affect human-protected session → guard prevents/flags  
**Rollback**: Remove guard logic; original behavior restored; HUD reverts to previous state  
**Charter Compliance**: **CRITICAL** — COMPANY_CHARTER.md rule 5: "Do not terminate human-owned or protected sessions." This is an absolute constraint.  
**Dependencies**: None (existing session data respected; new guard adds protection)  

**Implementation Steps**:
1. Create `session_guard.py` with `is_protected(session_id)` function
2. Integrate into `company.py dispatch()` — check before task assignment
3. Add HUD endpoint `/api/hud/workforce` protected-sessions count
4. Non-destructive test: Identify known human-protected sessions; verify guard blocks inappropriate operations

**Non-Destructive Test Command**:
```bash
# Verify guard identifies protected sessions correctly
python -c "from session_guard import is_protected; print(is_protected('human-session-123'))"
```

---

### Phase 5 — Verification Loop (P3, High Effort — Section 8 Mandate)

**Goal**: Build independent verification harness per Section 8: "A task is not complete merely because an agent says it is complete"  
**Success Criteria**: Verification run produces pass/fail verdict + evidence; independent second-model check optional; output stored in task record  
**Test**: Dispatch a task → run verification → verdict + evidence stored in task record  
**Rollback**: Disable verification; task record retains original output; no charter violations  
**Charter Compliance**: Section 8 QA dept mandate; all work must pass independent verification before reported complete  
**Dependencies**: Phase 2 (task registry) — verification stores results in task records  

**Implementation Steps**:
1. Create `verification.py` with `verify_task(task_id, output)` function
2. Verification checks: output completeness, cost deductions charter compliance, model failure flags
3. Optional: Independent second-model call for quality verification (per free-model strategy Rule 4)
4. Store `verification_status` + `verification_evidence` in task DB
5. Add `company.py verify-task` command
6. Non-destructive test: Create task with known output, verify produces correct verdict

**Non-Destructive Test Command**:
```bash
python company.py dispatch "test task for verification"
python company.py verify-task c-abc12345
```

---

### Phase 6 — HUD Data Endpoints (P3, High Effort — Section 8)

**Goal**: Create 7 HUD REST endpoints with real data (not fabricated) per Section 8  
**Success Criteria**: All 7 endpoints return real data from existing infrastructure; fallback empty states with warnings (never fabricated)  
**Test**: `curl http://localhost:4749/api/hud/executive` → real data or empty state with warning  
**Rollback**: Remove HUD endpoints; session control panel reverts to previous state; no charter violations  
**Charter Compliance**: Section 8 explicit mandate: "The HUD must show real operational data, not fabricated healthy statuses or placeholder numbers"  
**Dependencies**: Phase 2 (task registry) for task data; office-os Fastify for metrics; session-control-panel React UI  

**Implementation Steps**:
1. Create Fastify HUD routes in `AI-Office/unified-api/src/` (or appropriate location)
2. Endpoint 1: `/api/hud/executive` — pull from `company.py status` + `logs/company.log`
3. Endpoint 2: `/api/hud/workforce` — agent/session status from `.openalice-fleet/` + `.agents/`
4. Endpoint 3: `/api/hud/tasks` — task DB query
5. Endpoint 4: `/api/hud/departments` — per-department metrics from department handlers
6. Endpoint 5: `/api/hud/models` — free-model-inventory + cost tracking
7. Endpoint 6: `/api/hud/inbox` — classified inbox count + status
8. Endpoint 7: `/api/hud/quality` — verification status + failed checks
9. Add React UI updates to session control panel to consume these endpoints
10. Non-destructive test: `curl` each endpoint; verify real data or appropriate empty state

**Non-Destructive Test Command**:
```bash
cd /Users/aryanagarwal/AI-Office/packages/office-os
python core/web_server.py  # start Fastify server
curl http://127.0.0.1:8083/api/hud/executive
```

---

## Phase Gate Summary

| Phase | Gate | Go/No-Go Criteria |
|---|---|---|
| **Phase 1** | **Go** if | 5 sample inbox items classified correctly by human reviewer |
| **Phase 2** | **Go** if | Task record persistently stored + retrievable via `company.py task-status` |
| **Phase 3** | **Go** if | Model selection appears in dispatch output + cost deductions logged |
| **Phase 4** | **Go** if | Human-protected sessions correctly identified; guard prevents inappropriate operations |
| **Phase 5** | **Go** if | Verification produces pass/fail verdict + evidence stored in task record |
| **Phase 6** | **Go** if | All 7 HUD endpoints return real data or appropriate empty state (no fabrication) |

---

## Success Milestone (per Master Prompt Section 15)

> "My most important recommendation: Don't let your AI build another parallel office. Make Brain Bot the management layer over your existing Hive and fleet, with a genuinely unified task and inbox system.
> 
> The first milestone should be proving that one instruction can enter the office, reach an existing agent, produce a real deliverable, pass independent verification and appear as completed in the HUD."

### Milestone 1 — "One Instruction Completes"

**Criteria**: End-to-end flow verified:
1. Instruction enters via `company.py dispatch "task description" --department X`
2. Task routed to correct department via `company_dispatcher.py`
3. Department handler produces real deliverable (output stored in task DB)
4. Independent verification runs + produces pass/fail verdict + evidence
5. HUD displays task as completed with real data (not fabricated)

**Test**: Execute full flow with a research task — from dispatch → verification → HUD completion appearance.

---

## Implementation Timeline & Turn Order

| Phase | Estimated Turns | Risk Level | Charter Impact |
|---|---|---|---|
| Phase 1 — Inbox Classification | 2 turns | Low (text-only, no charter impact) | None — fully paper-safe |
| Phase 2 — Task Registry | 3 turns | Low (SQLite add-on, reversible) | None |
| Phase 3 — Model Router | 3 turns | Medium (model selection, cost tracking) | Cost-honest per charter rule 2 |
| Phase 4 — Session Guard | 3 turns | **Critical** (charter rule 5) | **Absolute** — PAPER ONLY constraint |
| Phase 5 — Verification Loop | 4 turns | High (Section 8 mandate) | Section 8 QA dept requirement |
| Phase 6 — HUD Endpoints | 5 turns | High (Section 8: no fabricated statuses) | Section 8 explicit mandate |

**Total Estimated**: 20 turns (this goal's entire budget)

**Recommendation**: Start with Phase 1 (Inbox Classification) — lowest risk, highest immediate value, proves the end-to-end flow the master prompt calls for. Each subsequent phase gates on the previous phase's success.

---

## Next Concrete Action

**Start with Phase 1 — Inbox Classification Pipeline** (2 turns estimated):

1. Create `AI-Office/classify_inbox.py` classification script
2. Run on 5 sample inbox items
3. Human review + approval
4. If approved, integrate output into task registry

This is the first of the 6 implementation phases and the first milestone toward proving "one instruction can enter the office, reach an existing agent, produce a real deliverable, pass independent verification and appear as completed in the HUD."

---

*End of Prioritized Implementation Plan (Deliverable 11)*