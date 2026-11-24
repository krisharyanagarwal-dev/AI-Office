# OPENALICE AI Office Architecture Research & Integration Design

**Status**: Research Complete → Unified Architecture Draft  
**Generated**: 2026-11-24  
**Purpose**: Classify candidate GitHub projects and integrate with frozen 10×10 Rev 2.4 configuration

---

## Executive Summary

This document presents the completed architecture research for the OPENALICE Autonomous AI Office, analyzing 5 major GitHub projects and producing a unified design that integrates with the existing AI-Office infrastructure while preserving the OpenAlice 10×10 Rev 2.4 "frozen" configuration.

### Key Findings

1. **License Compatibility Matrix** - 4 of 5 projects are viable for integration
2. **Architecture Patterns** - Identified 3 distinct patterns: CLI-agent, Swarm-world, Real-time multiplayer
3. **Integration Opportunities** - Specific components to extract and adapt
4. **10×10 Rev 2.4 Preservation** - Confirmed existing 6-department structure maps to proposed 10-department architecture

---

## 1. Repository Comparison Matrix

### License Classification

| Repository | License | Classification | Notes |
|---|---|---|---|
| **claw-empire** | Apache 2.0 | ✅ REUSE | Excellent candidate - CLI agents, Virtual Company, office packs |
| **MAYA-Office** | MIT | ✅ REUSE | Swarm coordination, shared world state model |
| **agent-office** | MIT | ✅ REUSE | Phaser.js + React, Colyseus multiplayer, Ollama integration |
| **ChatDev** | Apache 2.0 | ⚠️ INSPIRE | FastAPI + Vite+Vue, DevAll zero-code platform concepts |
| **agents-office (ajsahni)** | PolyForm Noncommercial 1.0.0 | ❌ REJECT | Restrictive - prohibits commercial use |

### Feature Comparison

| Feature | claw-empire | MAYA-Office | agent-office | ChatDev | OPENALICE Alignment |
|---|---|---|---|---|---|
| **CLI Agent Dispatch** | ✅ Core | ⚠️ Script-based | ✅ Colyseus CLI | ✅ Agent coordination | Integrate CLI dispatch layer |
| **Web UI** | ✅ Pixel-art office | ⚠️ Console-based | ✅ React + Phaser.js 3D | ✅ Vite+Vue frontend | Extend React session-control-panel |
| **Real-time Coordination** | ✅ Virtual Company | ✅ Swarm shared state | ✅ Colyseus multiplayer | ⚠️ REST polling | Adopt Colyseus pattern |
| **Task Queuing** | ✅ Office Packs | ✅ Swarm initiatives | ✅ Task system | ⚠️ Simple queue | Enhance with hypothesis_queue.py |
| **State Persistence** | ✅ SQLite | ✅ Shared world JSON | ✅ SQLite | ✅ SQLite | Already implemented (task registry) |
| **Model Agnostic** | ✅ Ollama support | ⚠️ GPT-4 focused | ✅ Ollama configurable | ⚠️ OpenAI primary | Integrate model_router.py |
| **Cost Tracking** | ⚠️ Basic | ⚠️ Not explicit | ⚠️ Not explicit | ⚠️ Not explicit | Use COST-HONEST framework |
| **Verification Loop** | ⚠️ Manual review | ⚠️ Peer review | ⚠️ Basic | ⚠️ Not explicit | Implement Phase 5 verification |

### Architecture Patterns Identified

| Pattern | Repositories | Strengths | Integration Strategy |
|---|---|---|---|
| **CLI-Agent Pattern** | claw-empire, ChatDev | Simple dispatch, easy automation | Use as foundation for company.py dispatch |
| **Swarm-World Pattern** | MAYA-Office | Scalable multi-agent coordination | Extract shared world state for department coordination |
| **Real-time Multiplayer Pattern** | agent-office | Live UI updates, collaborative | Extend session-control-panel with Colyseus |

---

## 2. 10×10 Rev 2.4 Configuration Analysis

### Current vs Proposed Structure

**Current (6 departments)**:
| Department | Role Count | Status |
|---|---|---|
| Executive & Planning | 1 coordinator | ✅ Implemented |
| Software Engineering | - | 🔄 Proposed |
| Research & Intelligence | 100 specialists | ✅ Active |
| Quality Assurance | - | 🔄 Proposed |
| Infrastructure | - | 🔄 Proposed |
| Data & Analytics | - | 🔄 Proposed |
| Business Operations | 6 families | 🔄 Partially mapped |
| Product & Design | - | 🔄 Proposed |
| Security | - | 🔄 Proposed |
| Trading Research | 10 managers, 389 specialists | ✅ Active (PAPER-only) |

**Mapping to existing AI-Office**:

| OpenAlice 10K Department | AI-Office Current | Mapping Status |
|---|---|---|
| Executive & Planning | Ops/Upgrade | ✅ Mapped |
| Software Engineering | Assistant | ✅ Partially mapped |
| Research & Intelligence | Research | ✅ Direct match |
| Quality Assurance | - | 🔄 New layer needed |
| Infrastructure | Ops/Fleet | ✅ Partial overlap |
| Data & Analytics | Research/Trading | 🔄 Extended |
| Business Operations | Research/Trading | 🔄 Extended |
| Product & Design | Assistant | ✅ Partially mapped |
| Security | - | 🔄 New layer needed |
| Trading Research | Trading | ✅ Direct match (PAPER-only) |

### Preservation Strategy

The existing 6-department structure preserves the "frozen" nature of 10×10 Rev 2.4 by:
1. Maintaining the core 3 departments that are active (Research, Trading, Assistant)
2. Keeping Ops/Upgrade for Executive+Infrastructure coordination
3. Preserving the PAPER-only constraint for Trading Research
4. Using keyword-based routing that maps to the 10K role templates

---

## 3. Integration Design

### Phase-by-Phase Integration

#### Phase 1: Inbox Classification (Immediate)

**Classified Inbox Items**:

| Item | Classification | Department | Action Required |
|---|---|---|---|
| `dispatcher.md` | AWAITING APPROVAL | Fleet | No action - auto-handled |
| `key-health.md` | ACTIONABLE | Ops | Monitor standing duty |
| `cost-auditor.md` | IN PROGRESS | Ops | Track cost deducted |
| `alerting.md` | INFORMATIONAL | - | Read-only |
| `weekly-reviewer.md` | ACTIONABLE | Research | Generate weekly report |

**Classification Scheme** (per Section 2):
- `INFORMATIONAL`: Status updates, documentation
- `ACTIONABLE`: Tasks requiring execution
- `AWAITING APPROVAL`: Pending human review
- `IN PROGRESS`: Active work items
- `RESOLVED`: Completed items
- `DUPLICATE`: Redundant tasks
- `BLOCKED`: Cannot proceed without dependencies

#### Phase 2: Model Router Integration

**Current Models Available** (from model-router.yaml):

| Model | Backend | Priority | Use Case |
|---|---|---|---|
| Qwen3.5-9B (MLX) | mlx-local | 100 | Primary research |
| Llama3.2:3b | mlx-local | 100 | Lightweight tasks |
| Nemotron-3.5 | nim-cloud | 50 | Creative tasks |
| qwen9 | free-harness | 10 | Fallback |

**Free Model Strategy** (per implementation-plan.md):
- Tier 1: Local Ollama/MLX models (cost: $0)
- Tier 2: Free API models (cost: minimal)
- Tier 3: Paid cloud models (cost-deducted)

#### Phase 3: Task Lifecycle State Machine

```
SUBMITTED → VALIDATING → QUEUED → LEASED → RUNNING → VERIFYING
                         |           |         |           |→ SUCCEEDED (after atomic commit)
                         |           |         |           |→ CORRECTION_QUEUED / NEEDS_REVIEW
                         |           |         |-> BLOCKED / RETRY_WAIT / NEEDS_APPROVAL
                         |           |-> lease expiry and reconciliation
                         |-> FAILED / DEAD_LETTER / REJECTED
                         |-> REJECTED

Cancellation: SUBMITTED → CANCELLED (after defined conditions)
```

---

## 4. Department Handler Integration

### Current Handlers (company_dispatcher.py)

```python
# Research Handler
hypothesis_queue.py, o3_runner.py, verdict_gate.py
→ Map to Quality Assurance + Research & Intelligence

# Trading Handler  
paper_trader.py, backtest_*.py
→ Preserve PAPER-only constraint

# Fleet Handler
JEV 32-agent dispatch
→ Integrate with session_guard.py

# Ops Handler
jev-dispatcher.py --pnl, metrics endpoint
→ Dashboard metrics + P&L

# Assistant Handler
General Claude capabilities
→ Software Engineering + Product/Design

# Upgrade Handler
upgrade_system.py
→ Executive + Security coordination
```

### Handler Integration Map

| Handler | GitHub Source | Integration |
|---|---|---|
| `handle_research()` | MAYA-Office swarm_bench concepts | Add hypothesis pre-registration |
| `handle_trading()` | ChatDev backtest patterns | Enforce PAPER-only + cost-honest |
| `handle_fleet()` | claw-empire Virtual Company | Integrate session guard |
| `handle_ops()` | Agent-office dashboard | Add HUD endpoints |
| `handle_assistant()` | ChatDev code generation | Add verification loop |
| `handle_upgrade()` | OpenAlice upgrade_system | Add charter verification |

---

## 5. Database Schema Design

### Task Registry (SQLite)

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    department_id TEXT,
    parent_task_id TEXT,
    idempotency_key TEXT,
    objective_ref TEXT,
    requested_capabilities TEXT,
    assigned_role_id TEXT,
    assigned_role_profile_version TEXT,
    dependency_ids TEXT,
    input_artifact_refs TEXT,
    input_hashes TEXT,
    acceptance_criteria_ref TEXT,
    policy_snapshot_id TEXT,
    budget_ceiling REAL,
    deadline TEXT,
    priority INTEGER,
    approval_state TEXT,
    status TEXT,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    output_evidence TEXT,
    verification_status TEXT,
    cost_deduction REAL,
    model_selected TEXT
);
```

### Verification Record

```sql
CREATE TABLE verification_records (
    verification_id TEXT PRIMARY KEY,
    task_id TEXT,
    execution_id TEXT,
    producer_identity TEXT,
    candidate_output_hashes TEXT,
    acceptance_criteria_ref TEXT,
    criteria_version TEXT,
    verifier_role_id TEXT,
    verifier_profile_version TEXT,
    verifier_runtime_id TEXT,
    verifier_identity TEXT,
    verifier_policy_snapshot_id TEXT,
    evidence_refs TEXT,
    check_results TEXT,
    decision TEXT,
    limitations TEXT,
    created_at TEXT
);
```

---

## 6. HUD Data Endpoints Specification

### Section 8 Compliance: Real Data Only (Never Fabricated)

| Endpoint | Data Source | Verification Required |
|---|---|---|
| `/api/hud/executive` | company.py status + logs/company.log | ✓ Task counts, delays |
| `/api/hud/workforce` | .openalice-fleet/ + session state | ✓ Protected session count |
| `/api/hud/tasks` | tasks.db | ✓ Real task records |
| `/api/hud/departments` | Department handlers | ✓ Current metrics |
| `/api/hud/models` | model-router.yaml + usage logs | ✓ Real model availability |
| `/api/hud/inbox` | _office/inbox/*.md | ✓ Real file count/status |
| `/api/hud/quality` | verification_records table | ✓ Real pass/fail rates |

---

## 7. Charter Compliance Verification

| Rule | Status | Implementation |
|---|---|---|
| **PAPER ONLY** | ✅ LOCKED | Kill switch disabled, live_orders_allowed=false |
| **COST-HONEST** | ✅ Active | All metrics include brokerage, STT, GST, stamps, slippage |
| **PRE-REGISTERED** | ✅ In Use | hypothesis_queue.py requires pre-registration |
| **VERIFIED** | 🔄 Implementing | Phase 5 verification loop |
| **SELF-UPGRADING** | ✅ Active | upgrade_system.py + self-upgrade rules |
| **NO CURVE-FITTING** | ✅ Enforced | Parameters locked post-results |

---

## 8. Integration Roadmap

### Immediate (Phase 1-2)
- [x] Repository classification complete
- [x] License analysis complete
- [ ] Create classify_inbox.py script
- [ ] Run classification on 5 sample items
- [ ] Create tasks.db schema
- [ ] Integrate task persistence into company_dispatcher.py

### Short-term (Phase 3-4)
- [ ] Integrate model_router.py with dispatch flow
- [ ] Implement session_guard.py for human-protected sessions
- [ ] Add task-status command to company.py

### Medium-term (Phase 5-6)
- [ ] Build verification.py with independent checking
- [ ] Implement 7 HUD REST endpoints
- [ ] Update session-control-panel to consume HUD APIs

---

## 9. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Agents-Office license incompatibility | Low | High | Already rejected - PolyForm Noncommercial |
| 10×10 Rev 2.4 configuration drift | Medium | High | Document role mapping, no runtime changes |
| Model router downtime | Low | Medium | Fallback to free-harness backend |
| HUD data fabrication | Low | Critical | Section 8 compliance check - real data only |
| Charter violation (live orders) | Very Low | Critical | Kill switch LOCKED, no broker connection |

---

## 10. Unresolved Decisions

1. **HUD ownership** - Canonical source currently unresolved (per 10K design)
2. **Clerk deployment** - Role assignment for trading clerks needs approval
3. **Data source integration** - TradingView vs yfinance vs nsepython priority
4. **Verification second model** - Which free model for independent verification?
5. **Budget ceiling values** - Currently unset per implementation plan

---

## 11. Deliverables Produced

1. ✅ Repository comparison matrix (completed)
2. ✅ License classification (completed)
3. ✅ 10×10 Rev 2.4 configuration preservation analysis (completed)
4. ✅ Integration design with department mapping (completed)
5. ✅ Task lifecycle state machine (documented)
6. ✅ Model router integration design (completed)
7. ✅ Database schema design (completed)
8. ⏳ Inbox classification pipeline (in progress - Phase 1)
9. ⏳ Task registry implementation (Phase 2 pending)
10. ⏳ Session guard implementation (Phase 4 pending)
11. ⏳ Verification loop (Phase 5 pending)
12. ⏳ HUD endpoints (Phase 6 pending)

---

## Conclusion

The OPENALICE architecture research is complete. The existing AI-Office infrastructure aligns well with the 10K Office design, requiring primarily integration of the classified components from claw-empire, MAYA-Office, and agent-office (all MIT/Apache 2.0 licensed). The frozen 10×10 Rev 2.4 configuration is preserved through the existing 6-department structure that maps to the proposed 10-department architecture.

The implementation can proceed with Phase 1 (Inbox Classification) as the first deliverable, followed by the task registry, model router integration, session guard, verification loop, and HUD endpoints as outlined in the implementation plan.