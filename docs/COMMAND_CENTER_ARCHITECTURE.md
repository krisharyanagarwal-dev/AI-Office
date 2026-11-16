# Command Center Architecture & Implementation Plan

## Executive Summary

Build a minimal central Command Center that synchronizes **OpenCode + Hermes + Deep Agents + NeMo Fabric + OpenShell + GitHub** using:
- **Nemotron 550B** (current model) for MASTER planning/deep reasoning ONLY
- **Fastest VERIFIED FREE NVIDIA cloud model** via `nv-route` skill for execution
- **Automatic free-model failover** via multiple NVIDIA API keys
- **No paid models, no OpenRouter, no local inference**
- **GitHub as persistent source of truth** (both projects have remotes)
- **State preservation** so new terminals understand what others are doing

---

## Current Environment Inventory

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| **Nemotron 550B** | ✅ Active | Current model | nvidia/nemotron-3-ultra-550b-a55b |
| **OpenCode** | ✅ Installed | `~/.opencode/` | @opencode-ai packages, minimal config |
| **Hermes** | ⚠️ Partial | `~/.hermes/` | Gateway failing (WhatsApp not paired) |
| **OpenAlice** | ✅ Installed | `~/.openalice/`, `~/openalice/` | Fleet state, UI |
| **Deep Agents** | ❌ Missing | - | Need to integrate |
| **NeMo Fabric** | ❌ Missing | - | Need to integrate |
| **OpenShell** | ❌ Missing | - | Need to integrate |
| **GitHub CLI** | ✅ Authenticated | `gh` | Account: goodwearrinfo-aryan |
| **NVIDIA API Keys** | ✅ 4 keys | `.env` | Primary + 3 fallbacks |
| **nv-route skill** | ✅ Available | `~/.claude/skills/nv-route/` | Routes to free NVIDIA workers |

### Projects

| Project | Type | Git Remote | Structure |
|---------|------|------------|-----------|
| **deepseek-harness** | TypeScript/Node.js (pnpm) | ✅ `github.com/deepseek-ai/deepseek-harness` | Cordis agent harness, 40+ packages |
| **wifi_security_bot** | Python | ❌ No git (has backup symlink) | Assessment, core, dashboard, monitoring |

---

## Architecture Design

### Core Principles

1. **GitHub = Source of Truth** — All state, config, coordination persisted to GitHub repos
2. **Nemotron = Planner Only** — Never executes, only produces plans/decisions
3. **nv-route = Executor** — All execution via free NVIDIA workers with failover
4. **Stateless Workers** — Workers read/write state from GitHub, not local memory
4. **Project Isolation** — Each project independent; Command Center coordinates
5. **No App Code Changes** — Integration via config, hooks, wrappers only

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMMAND CENTER (Nemotron)                    │
│  • Master planning & deep reasoning                             │
│  • Reads GitHub state → produces execution plans               │
│  • Delegates to nv-route workers                               │
└─────────────────────┬───────────────────────────────────────────┘
                      │ Plans (JSON)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    NV-ROUTE ORCHESTRATOR                        │
│  • Receives plans from Command Center                          │
│  • Spawns nv-* workers (judge/summarize/extract/generate/etc)  │
│  • Automatic failover across 4 NVIDIA API keys                 │
│  • Returns results with provenance                             │
└─────────────────────┬───────────────────────────────────────────┘
                      │ Tasks/Results
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌───────────────┐ ┌───────────┐ ┌──────────────┐
│  Project A    │ │ Project B │ │  Shared      │
│ deepseek-     │ │ wifi_sec- │ │ Infrastructure │
│ harness       │ │ urity_bot │ │              │
│               │ │           │ │ • GitHub     │
│ • OpenCode    │ │ • OpenCode│ │ • Hermes     │
│ • Hermes      │ │ • OpenAlice│ │ • NeMo Fabric│
│ • NeMo Fabric │ │ • Deep Ag │ │ • OpenShell  │
│ • OpenShell   │ │ • NeMo    │ │ • State Sync │
└───────────────┘ └───────────┘ └──────────────┘
```

### State Management (GitHub as Source of Truth)

Each project gets a **command-center/** directory in its repo:

```
/deepseek-harness/
  command-center/
    state.json          # Current coordination state
    workers/            # Worker assignments & status
    plans/              # Nemotron-generated plans
    logs/               # Execution logs
    config.yaml         # Project-specific config

/wifi_security_bot/
  command-center/
    state.json
    workers/
    plans/
    logs/
    config.yaml
```

Global coordination state in a **dedicated repo** or **gist**:
- `command-center-global/` — cross-project coordination, shared workers, global config

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

#### 1.1 Command Center Core
- [ ] Create `command-center/` package in deepseek-harness (TypeScript)
- [ ] Create `command_center/` package in wifi_security_bot (Python)
- [ ] Shared TypeScript/Python types for state schema
- [ ] GitHub state persistence layer (read/write JSON to repo via gh CLI)

#### 1.2 NV-Route Integration
- [ ] Wrap `nv-route` skill as callable library
- [ ] Implement automatic failover across 4 NVIDIA API keys
- [ ] Add request/response logging with provenance
- [ ] Create worker pool manager (max concurrent workers configurable)

#### 1.3 State Schema
```json
{
  "version": "1.0",
  "project": "deepseek-harness|wifi_security_bot",
  "updated_at": "ISO8601",
  "master_plan": { ... },
  "workers": [
    {"id": "w1", "type": "nv-generate", "status": "running|done|failed", "task": "...", "result": {...}}
  ],
  "integrations": {
    "opencode": {"enabled": true, "config": {...}},
    "hermes": {"enabled": true, "config": {...}},
    "nemo_fabric": {"enabled": false, "config": {...}},
    "openshell": {"enabled": false, "config": {...}},
    "deep_agents": {"enabled": false, "config": {...}}
  }
}
```

### Phase 2: Integrations (Week 2)

#### 2.1 OpenCode Integration
- [ ] Create `.opencode/command-center.yaml` config per project
- [ ] Hook into OpenCode's agent/spawn system
- [ ] Sync OpenCode session state to GitHub

#### 2.2 Hermes Integration
- [ ] Fix WhatsApp pairing (or disable if not needed)
- [ ] Expose Hermes gateway as callable service
- [ ] Sync agent states to Command Center

#### 2.3 NeMo Fabric Integration
- [ ] Install NeMo Fabric (pip install nemo-fabric)
- [ ] Create adapter for Command Center task delegation
- [ ] Use for LLM fine-tuning/evaluation tasks

#### 2.4 OpenShell Integration
- [ ] Install OpenShell
- [ ] Create terminal/session management bridge
- [ ] Enable multi-terminal coordination

#### 2.5 Deep Agents Integration
- [ ] Define Deep Agent specification
- [ ] Create spawner that uses nv-route for execution
- [ ] Register agents in Command Center registry

### Phase 3: Coordination & Testing (Week 3)

#### 3.1 Multi-Terminal Coordination
- [ ] Terminal registration & heartbeat system
- [ ] Conflict resolution for concurrent operations
- [ ] New terminal "catch-up" protocol (read GitHub state)

#### 3.2 Testing & Validation
- [ ] Test deepseek-harness coordination
- [ ] Test wifi_security_bot coordination
- [ ] Test cross-project isolation
- [ ] Failover testing (simulate NVIDIA API failures)
- [ ] Load testing (multiple concurrent workers)

#### 3.3 Documentation & Handoff
- [ ] Architecture decision records
- [ ] Operations runbook
- [ ] Integration guides for each tool

---

## Technical Specifications

### Nemotron (Master) Responsibilities
- Read GitHub state → analyze → produce execution plan
- Decide which workers to spawn, in what order, with what parameters
- Handle high-level decisions: "should we scale workers?", "which integration to use?"
- Never execute tasks directly

### NV-Route Workers (Executors)
Each worker type maps to nv-route agent:

| Worker Type | nv-route Agent | Use Case |
|-------------|----------------|----------|
| Planner | nv-generate | Create detailed task breakdowns |
| Coder | nv-generate | Write code, configs, scripts |
| Reviewer | nv-judge | Validate outputs, check correctness |
| Summarizer | nv-summarize | Condense logs, outputs |
| Extractor | nv-extract | Parse structured data from outputs |
| Classifier | nv-classify | Categorize issues, prioritize tasks |
| QA | nv-qa | Answer questions from context |
| Translator | nv-translate | Cross-language tasks |

### Failover Strategy
```
Primary: NVIDIA_API_KEY (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)
Fallback 1: NVIDIA_API_KEY_FALLBACK
Fallback 2: NVIDIA_API_KEY_FALLBACK2
Fallback 3: NVIDIA_API_KEY_FALLBACK3
```
- On any failure (timeout, 4xx, 5xx), automatically retry with next key
- Log failover events with provenance
- After all failovers exhausted → mark task failed, alert

### GitHub Sync Protocol
- **Push**: After each state change, commit to `command-center/` branch
- **Pull**: On startup, every 30s, and before any major decision
- **Conflict**: Last-write-wins with timestamp; log conflicts for review
- **Branch**: `command-center/state` (protected, force-push allowed for sync)

---

## Project-Specific Configurations

### deepseek-harness (TypeScript)
```yaml
# command-center/config.yaml
project: "deepseek-harness"
language: "typescript"
package_manager: "pnpm"
integrations:
  opencode:
    enabled: true
    profile: "headless"
    config_path: ".opencode/command-center.yaml"
  hermes:
    enabled: true
    gateway_url: "http://localhost:8080"  # or unix socket
  nemo_fabric:
    enabled: true
    use_case: "model_eval"
  openshell:
    enabled: true
    sessions: 4
  deep_agents:
    enabled: true
    max_concurrent: 3
```

### wifi_security_bot (Python)
```yaml
# command-center/config.yaml
project: "wifi_security_bot"
language: "python"
package_manager: "pip"
integrations:
  opencode:
    enabled: true
    profile: "python"
  hermes:
    enabled: false  # Not needed for this project
  nemo_fabric:
    enabled: true
    use_case: "security_model_training"
  openshell:
    enabled: true
    sessions: 2
  deep_agents:
    enabled: true
    max_concurrent: 2
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| NVIDIA API all fail | Queue tasks, alert, retry with exponential backoff |
| GitHub sync conflicts | Timestamp-based resolution, conflict log |
| Hermes gateway down | Graceful degradation, mark integration unhealthy |
| Worker runaway | Timeout enforcement, max concurrent limits |
| State corruption | Git history as backup, checksum validation |

---

## Next Steps

1. **Review this plan** — Confirm architecture aligns with requirements
2. **Phase 1 implementation** — Start with Command Center core + NV-Route wrapper
3. **Incremental testing** — Test each integration independently
4. **No Mac mini deployment** — Until explicit approval

---

## File Structure (To Be Created)

```
deepseek-harness/
  packages/
    command-center/           # NEW: TypeScript package
      src/
        index.ts              # Main entry
        state/                # State management
        github/               # GitHub persistence
        nvroute/              # NV-Route wrapper
        integrations/         # Integration adapters
        workers/              # Worker pool manager
      tests/
      package.json

wifi_security_bot/
  command_center/             # NEW: Python package
    __init__.py
    state.py
    github.py
    nvroute.py
    integrations/
    workers/

# Global (optional separate repo)
command-center-global/
  config.yaml
  shared-workers.yaml
```

---

*Generated by Nemotron 550B (Master Planner) — Ready for implementation*