# Missing Integrations and Critical Operational Risks

**Based on**: Master System Prompt Section 15 (Make the Office Real) — Discovery audit items 9 & 10  
**Generated**: 2026-11-23  
**Purpose**: Discovery audit — missing integrations and critical operational risks

---

## 9. Missing Integrations

Per the master prompt's 8-department structure and the goal of making the existing infrastructure operate as one unified AI Office, these are the key integrations that are currently missing:

### 1. Inbox → Department Classification Pipeline (P0)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| _office/inbox classification | 60+ items unclassified (all marked actionable but no formal classification) | Build classification pipeline per Section 2 of master prompt (INFORMATIONAL/ACTIONABLE/AWAITING APPROVAL/IN PROGRESS/RESOLVED/DUPLICATE/BLOCKED) | All task routing depends on this — entry point for all work |
| Inbox → task ID conversion | No pipeline exists | Create inbox-to-task converter that classifies + generates task records in central registry | Without this, no centralized task management |

### 2. Central Task Registry (P1)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| Persistent task IDs | `c-<8hex>` generated per dispatch, lost after console output | Create task database (SQLite like `office-core/tasks.db`) with UUIDs, status, deadlines, dependencies | Enables status tracking, cross-dispatch consistency, verification |

### 3. Cross-Department Task Routing (P1)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| Department dependency tracking | No inter-department dependencies tracked | Add `dependencies` field to task records; route considering prerequisites | Enables complex workflows across multiple departments |

### 4. Model Router Integration (P2)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| Free-model inventory → task routing | Model inventory exists (free-model-inventory.md) but not used by dispatcher | Integrate model router into `company_dispatcher.py` — select model per task based on allocation table | Enables intelligent model selection per the free-model strategy (Section 4) |

### 5. Memory Bridge (P2)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| User-scope ↔ project-scope MEMORY.md sync | 4 user entries + 7 project entries, no connection | Create sync script that propagates changes between both memory scopes | Ensures consistent state across conversation contexts |

### 6. Agent Capability Map (P2)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| No "what each agent can do" registry | Agents exist (JEV fleet, OpenCode, Dost) but capabilities undocumented | Build `agent-capability-matrix.md` mapping agent types → capabilities → autonomy tier | Enables capability-aware task assignment (replaces keyword-only routing) |

### 7. Verification Loop (P3 — Critical/Section 8)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| Independent verification pipeline | No verification infrastructure (Section 8: "A task is not complete merely because an agent says it is complete") | Build verification harness with independent second-model checks | Per Section 8 QA dept mandate; prevents undetected failures |

### 8. Decision History (P3)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| No decision outcomes recorded | Decisions made informally, no persistent record | Create decision history registry with decision_id, date, department, objective, outcome, lessons learned | Per Section 7: "Decision history" and "Lessons learned" required |

### 9. Agent Memory Protocol (P3 — Section 7)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| No explicit shared storage for agent memory | Per Section 7: "Never assume that an agent's private memory is automatically visible to other agents" | Define per-agent memory format + shared storage mechanism | Ensures agent memory visibility across the office |

### 10. Priority Escalation (P3)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| No automated priority escalation | Manual human selection via `--department` flag only | Add auto-escalation based on task age, keyword severity, department | Enables autonomous operation per Section 5 (STEP 5: MONITOR) |

### 11. HUD Data Endpoints (P3 — Section 8)

| Missing Integration | Current State | Required Action | Impact |
|---|---|---|---|
| 0/7 HUD endpoints implemented | Session control panel React app + Fastify metrics exist but no HUD-specific endpoints | Create 7 REST endpoints: `/api/hud/{executive,workforce,tasks,departments,models,inbox,quality}` | Per Section 8: HUD must show real operational data, not fabricated healthy statuses |

---

## 10. Critical Operational Risks

Per the master prompt's constraints (COMPANY_CHARTER.md) and the discovery audit, these are the critical operational risks:

### 1. Charter Violation Risk: Live Orders Through Paper-Only System

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Code path accidentally adds live order path | Low (charter gated) | **Critical** (real capital deployment) | COMPANY_CHARTER.md rule 1: "PAPER ONLY — Kill switch LOCKED. No order path ever added." Enforce via code review + charter audit |

### 2. Fabricated Healthy Statuses (HUD Display Risk)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| HUD shows fabricated metrics instead of real data | Medium | **High** (per Section 8: "The HUD must show real operational data, not fabricated healthy statuses or placeholder numbers") | Section 8 mandate: All HUD data must come from real endpoints; never fabricate; fallback to empty state with warning |

### 3. Model Cost Overrun (Cost-Honest Violation)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Expensive model calls on simple tasks, cost deductions not tracked | Medium | **High** (charter rule 2: "COST-HONEST — All research deducts Groww costs") | Free-model strategy Rule 3: "Avoid wasting expensive model calls on simple work"; Rule 7: "Never claim a model is free without verifying actual pricing and limits" |

### 4. Agent Session Forking (Cross-Machine State Risk)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Laptop + Mac mini silently forked, work not synced | Medium (per project memory) | **High** (700+ row queue, unstartable agents) | Project memory notes: "silently forked"; use `gated-multi-machine-git-sync`; `mini-fleet-deploy-verify` to prove sync |

### 5. Agent Failure Undetected (No Taxonomy)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agent fails silently, no failure tracking | High (no taxonomy, no monitoring) | **Medium** (tasks appear complete but are broken) | Per systematic-debugging skill: create failure taxonomy; per Section 8: detect + report failures |

### 5. Inbox Duplication (No Dedup Pipeline)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Same task dispatched multiple times | Medium (60+ unclassified inbox items) | **Medium** (wasted compute, confused task status) | Per Section 2: classification includes DUPLICATE; add dedup in task registry |

### 6. Model Failure Cascade (No Retry Logic)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Model fails, task fails completely, no retry with alternative | Medium (per free-model strategy Rules 5-6) | **Medium** (downtime, delayed deliverables) | Free-model strategy Rules 5-6: "Retry with another available model when a provider fails"; "Track model failures and rate limits" |

### 7. Rate Limit Exhaustion (API Provider Risk)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Provider rate limits exceeded, task failures | Low-Medium (no tracking) | **Medium** (compute downtime, cost overruns from retries) | Free-model strategy Rules 5-6: "Track model failures and rate limits"; implement per-provider rate limit tracker |

### 8. Memory Staleness (Decaying Knowledge)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| MEMORY.md entries become outdated, no validation | High (no validation mechanism) | **Low-Medium** (wrong assumptions in future sessions) | Per auto-memory system: "Update or remove memories that turn out to be wrong or outdated"; "Before answering, verify memory is still correct and up-to-date" |

### 9. Deprecated Code Retention (Maintenance Risk)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Old code/deleted files remain in repo, confusion about what's active | Medium (git history shows deleted files) | **Medium** (accidental use of deprecated code) | Per `build-on-what-works` skill: "Before writing new code, check if something already exists that can be reused"; also: regularly clean up deleted/unused code |

### 10. Session Protection Bypass (Charter Critical)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Human-protected sessions not respected in automation | Low-Medium (charter rule 5) | **Critical** (charter violation, loss of human oversight) | COMPANY_CHARTER.md rule 5: "Do not terminate human-owned or protected sessions"; implement explicit guard in all automation |

---

## Integration + Risks Summary

### Integration Priority (from highest to lowest value)

| Priority | Missing Integration | Risk Addressed | Effort | First-Testable-Stage |
|---|---|---|---|---|
| **P0** | Inbox classification pipeline | Duplication, misrouting | Medium | Classify 5 sample inbox items; verify classifications make sense |
| **P1** | Central task registry | No status persistence, no cross-dispatch consistency | High | Create task DB schema; test: persist + retrieve task record |
| **P2** | Model router integration | Suboptimal model use, cost inefficiency | Medium | Integrate model selector into dispatcher; test: task routed to correct model class |
| **P2** | Memory bridge (user ↔ project scope) | Stale assumptions across contexts | Medium | Sync one entry between both MEMORY.md files; verify propagation |
| **P2** | Agent capability map | Keyword-only routing, missed capabilities | Medium | Build matrix for 3 agent types; test: task assigned to capable agent |
| **P3** | Verification loop (Section 8) | Undetected failures, charter violation | **High** (mandate) | Build independent verification for 1 task type; test: verification catches intentional error |
| **P3** | Decision history registry | No lessons learned, repeated mistakes | Low-Medium | Create decision record for this session; test: persists across turns |
| **P3** | Agent memory protocol | Agent memory not visible across agents | Low-Medium | Define memory format for 1 agent type; test: memory readable by another agent |
| **P3** | Priority escalation | No autonomous prioritization | Medium | Add age-based escalation; test: task auto-escalated after threshold |
| **P3** | HUD data endpoints | Fabricated statuses risk | High (Section 8) | Create 1 HUD endpoint; test: returns real data, no fabrication |
| **P3** | Inbox dedup pipeline | Wasted compute, confused status | Medium | Add dedup field to task registry; test: duplicate inbox items not double-dispatched |
| **P4** | Priority escalation automation | No autonomous workflow | Medium | Add escalation based on task age | 
| **P4** | HUD full dashboard | 7-section display | High (Section 8) | Implement 1 HUD section end-to-end |

### Risks Priority (from most to least critical)

| Priority | Risk | Charter Impact | Section Impact | Required Fix |
|---|---|---|---|---|
| **P0** | Fabricated healthy statuses (HUD) | ⚠️ Section 8 explicit mandate | Section 8 QA dept | Never fabricate; real data or empty state |
| **P0** | Charter violation: live orders | ⚠️ Absolute charter rule 1 | Section 15 PAPER ONLY | Enforce kill switch LOCKED; no live order path |
| **P0** | Human-protected session bypass | ⚠️ Charter rule 5 critical | Section 4 Agent Workforce | Explicit session protection in all automation |
| **P1** | Model cost overrun | ⚠️ Charter rule 2 cost-honest | Section 4 Free-model strategy | Free-model router + cost tracking |
| **P1** | Agent session forking | ⚠️ Project memory risk | fleet-orchestration audit | gated-multi-machine-git-sync + verification |
| **P1** | No verification pipeline | ⚠️ Section 8 QA dept mandate | Section 8 Quality dept | Build independent verification harness |
| **P2** | No agent capability map | ⚠️ Efficiency, not charter | Section 4 Agent Workforce | Build + use capability matrix |
| **P2** | No memory bridge | ⚠️ Stale knowledge, not charter | Section 7 Shared memory | Create sync protocol between scopes |
| **P2** | No failure taxonomy | ⚠️ Operational inefficiency | Systematic debugging | Document + track failure types |
| **P3** | Model rate limit exhaustion | ⚠️ Cost, downtime | Free-model strategy Rules 5-6 | Rate limit tracker + backoff |
| **P3** | Inbox duplication | ⚠️ Wasted compute, not charter | Section 2 Classification | Add DUPLICATE classification + dedup |
| **P3** | Rate limit exhaustion | ⚠️ Cost, downtime | Free-model strategy Rules 5-6 | Rate limit tracker + backoff |
| **P4** | Memory staleness | ⚠️ Knowledge decay, not charter | auto-memory system | Regular validation + cleanup |

---

## Completion Audit Checklist for Deliverables 9 & 10

| Checklist Item | Status | Evidence |
|---|---|---|
| Missing integrations documented (11 items) | ✅ Complete | `missing-integrations-risks.md` with 11 integrations |
| Critical operational risks documented (10 risks) | ✅ Complete | `missing-integrations-risks.md` with 10 risks |
| Each integration mapped to priority + effort | ✅ Complete | Priority/effort table with P0-P4 + Medium/High |
| Each risk mapped to charter section + mitigation | ✅ Complete | Risk table with likelihood/impact/mitigation |
| All 11 master prompt deliverable categories covered | ⚠️ 2/11 (9+10 of 11) | Still need deliverables 11 (implementation plan) |

---

*End of Missing Integrations and Critical Operational Risks*