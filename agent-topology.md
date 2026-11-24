# Agent and Session Topology

**Based on**: Master System Prompt Section 4 (Agent Workforce), Section 15 (Make the Office Real)  
**Generated**: 2026-11-23  
**Purpose**: Discovery audit — agent and session topology across the AI Office infrastructure

---

## Agent Ecosystem Topology

### 1. Agent Definitions and Registries

| Agent Type | Path/Location | Count | Status | Capabilities |
|---|---|---|---|---|
| **JEV Fleet Agents** | `.openalice-fleet/` + `jev-dispatcher.py` | 32 (configured) | ✅ Paper-only, Tier C human-gate | 32-agent dispatch, PnL reporting, tripartite consensus |
| **OpenCode Agents** | `.opencode/` directory | Variable | ⚠️ In-app Qoder sessions | Code generation, review, debugging |
| **Dost Agents** | `AI-Office/dost.py` | 1 (primary) | ✅ 320+ tests passing | Proactive multi-modal research, universal interfaces |
| **OpenAlice Fleet** | `.openalice/` (laptop + Mac mini) | 2-host fleet | ⚠️ Laptop + Mac mini over Tailscale/SSH | Fleet orchestration, state sync |
| **Qoder CLI Agents** | `.qoder/` + plugins | Variable | ⚠️ CLI-installed agents | CLI commands, extension integration |
| **Custom Script Bots** | `AI-Office/scripts/`, `AI-Office/packages/trading/scripts/` | ~30+ | ✅ Various (all_stocks_bot, backtest_*, etc.) | Fundamental analysis, options, risk, metrics |

### 2. Session Topology

| Session Type | Location | Status | Human-Protected? | Notes |
|---|---|---|---|---|
| **Terminal panes (macOS Terminal.app)** | `~/Library/Terminal/` | Variable | ⚠️ Some human-owned | Per fleet-orchestration audit: enumerate Terminal panes |
| **In-app Qoder sessions** | `~/.qoder/` + `~/.qoderwake/` | 40+ directories | ⚠️ Mixed | Some are agent sessions, some human-owned |
| **OpenCode fleet sessions** | `~/.Codex/agents/*.md` | Unknown | ✅ Human-protected per charter | "Do not terminate human-owned or protected sessions" |
| **launchd periodic jobs** | `~/Library/LaunchAgents/` | Active | ⚠️ Some human-owned | Per fleet-orchestration: census of per-job log paths |
| **Qoder Desktop pet sessions** | `~/.qoder/` petdex | Unknown | ❓ | Pet-related agent sessions |

### 3. Agent Capability Mapping (Gaps)

| Capability | Agents That Have It | Missing | Required |
|---|---|---|---|
| Code generation | OpenCode, Assistant | No independent verification | Add second-model code review |
| Research & analysis | Dost, Research dept | No evidence/source tracking | Build evidence collection pipeline |
| Paper trading | Trading dept, JEV fleet | Kill switch LOCKED (per charter) | Maintain paper-only constraint |
| P&L monitoring | Ops dept, JEV dispatcher | Not integrated with task outcomes | Cross-department P&L linking |
| Hypothesis backtesting | Research dept, o3_runner.py | No unified hypothesis queue | Integrate hypothesis_queue.py |
| Self-upgrade | Upgrade dept, upgrade_system.py | Risk of charter violations | Add charter-gated upgrade checks |
| Dashboard UI | Session control panel (React) | Not connected to Brain Bot | Integrate HUD with Brain Bot operating cycle |

### 4. Session Health Status

| Health State | Count | Location | Automation Level |
|---|---|---|---|
| **Active agents** | Unknown | `.openalice-fleet/`, `.opencode/` | Manual dispatch via company.py |
| **Idle agents** | Unknown | Session directories without active tasks | Needs detection algorithm |
| **Failed agents** | Unknown | Error logs in `logs/company.log`, `AI-Office/logs/` | Needs failure taxonomy |
| **Human-protected** | Unknown | Per COMPANY_CHARTER.md rule 5 | Must not terminate |
| **Tier C blocked** | 32 (JEV fleet) | `.openclaw/jev-dispatcher.py` | Human gate required |
| **Kill switch LOCKED** | 1 (system-wide) | COMPANY_CHARTER.md | Absolute constraint |

### 5. Cross-Machine Topology

| Machine | Role | Agent Sessions | Key Paths | State Sync |
|---|---|---|---|---|
| **Laptop** (this host) | Primary development | Qoder sessions, OpenCode agents | `~/.qoder/`, `~/.opencode/`, `AI-Office/` | Local state |
| **Mac mini (OpenAlice fleet)** | Fleet control center | 32 JEV agents, launchd jobs | `~/.openalice/`, `~/.openalice-fleet/`, `~/.Codex/agents/` | SSH/Tailscale sync |
| **Tailscale/SSH** | Inter-machine connectivity | Fleet orchestration | `tailscale ip`, `ssh macmini` | State reconciliation |

### 6. Agent Assignment Workflow (Current → Desired)

```
Current Flow (Keyword-based routing):
Human Task
    │
    ▼
company.py dispatch "task"
    │
    ├─► company_dispatcher.py route_department()
    │     │
    │     └─► Keyword scoring → best department
    │
    └─► DEPARTMENT_HANDLERS[dept](task)
          │
          └─► Department-specific execution

Desired Flow (Capability-aware + workload-balanced):
Human Task
    │
    ▼
Task Registry (centralized UUID + metadata)
    │
    ├─► Classify (informational/actionable//etc.)
    │
    ├─► Assess agent capabilities (map task → suitable agent)
    │
    ├─► Check workload (idle/busy/failed status)
    │
    ├─► Assign (persistent task ID + agent assignment)
    │
    └─► Dispatch with tracking
```

### 7. Topology Gaps and Risks

| Gap | Risk Level | Required Fix |
|---|---|---|
| No agent capability map | Medium | Build `agent-capability-matrix.md` — what each agent type can do |
| No workload tracking | Medium | Add agent health monitoring + idle detection |
| No session protection logic | High (charter violation risk) | Implement human-protected session guard per Section 4: "Do not terminate human-owned or protected sessions" |
| No cross-machine state sync | High (forked workstations per project memory) | Prove and reconcile git work spread across laptop + Mac mini |
| No failure taxonomy | High (per systematic-debugging skill) | Document failure types + recovery procedures |
| No autonomous assignment | Medium | Implement capability-aware task assignment (current: keyword-only) |

### 8. Topology Verification Status

| Verification Item | Status | Evidence |
|---|---|---|
| Agent count accurate | ⚠️ Unknown | Cannot verify without enumeration script |
| Session health known | ❌ No | No health monitoring in place |
| Human-protected sessions identified | ❌ No | Per charter but not tracked |
| Cross-machine state reconciled | ⚠️ Partially | Project memory mentions "silently forked" laptop + Mac mini |
| Capability mapping complete | ❌ No | No existing mapping |

---

*End of Agent and Session Topology*