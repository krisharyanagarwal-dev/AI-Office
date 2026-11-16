# SYSTEM AUDIT — Universal GitHub AI Workspace Orchestrator

## Machine Profile
- **OS**: macOS 26.5.2 (Darwin 25.5.0), ARM64 (Apple Silicon)
- **Shell**: zsh (xterm-256color)
- **Package Manager**: Homebrew (`/opt/homebrew/bin/brew`)
- **Node**: v22.22.3 (via nvm)
- **npm**: bundled with Node
- **Python**: 3.14.0 (`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`)
- **Git**: system (`/usr/bin/git`)
- **GitHub CLI**: `gh` v2.x (`/Users/aryanagarwal/.local/bin/gh`) — authenticated as `goodwearrinfo-aryan` with scopes: `repo`, `workflow`, `gist`, `read:org`, `delete_repo`
- **SSH**: Ed25519 keys for GitHub (`~/.ssh/id_ed25519_github`)

---

## Repository Inventory

| Repository | Path | Language | Git Remote | Description |
|------------|------|----------|------------|-------------|
| **trading-bot** | `/Users/aryanagarwal/trading-bot` | Python | `github.com/goodwearrinfo-aryan/trading-bot` | Crypto trading bot with backtesting, risk management, live adherence |
| **deepseek-harness** | `/Users/aryanagarwal/deepseek-harness` | TypeScript/Node (pnpm) | `github.com/deepseek-ai/deepseek-harness` | Multi-agent task orchestration, model router, worktree manager |
| **munder-difflin** | `/Users/aryanagarwal/munder-difflin` | TypeScript/React/Electron | `github.com/chaitanyagiri/munder-difflin` | Electron app with blog, landing page, remotion |

---

## Existing Orchestration Systems

### 1. Hermes (`~/.hermes/`) — PRIMARY AGENT PLATFORM
- **State DB**: SQLite (`state.db`) — sessions, messages, tool calls, costs
- **Config**: `config.yaml` — model routing (NVIDIA Nemotron via OpenCode), compression, delegation, kanban
- **Universal Workspace**: `~/.hermes/universal-workspace/` — **CLI already exists** (`workspace` command)
  - Packages: `cli`, `agents`, `ci`, `context`, `deployment`, `git`, `github`, `models`, `orchestration`, `retrieval`, `security`, `sessions`, `tasks`, `workspace`
  - CLI commands: `repos`, `sync`, `open`, `status`, `task`, `plan`, `doctor`, conversational mode
- **Kanban**: `kanban.db` + workspaces — task boards
- **Sessions**: `~/.hermes/sessions/` — request dumps
- **Model Routing**: NVIDIA Nemotron (master: 3-ultra, worker: 3.5-lightning) via OpenCode zen endpoint
- **Secret Redaction**: Built-in (tirith pre-exec scanning)

### 2. Deepseek-Harness Task System (`~/.deepseek-harness/.task/`)
- **TypeScript Model Router** (`model-router.ts`) — Free NVIDIA models with:
  - Roles: THINKING, EXECUTION, AUDIT
  - Automatic failover with exponential backoff
  - Error classification (RATE_LIMIT, TIMEOUT, PROVIDER_UNAVAILABLE, AUTH_FAILURE, etc.)
  - Cooldown tracking per model
- **Master Agent** (`master-agent.ts`) — orchestrates worker agents
- **Worktree Manager** (`worktree-manager.ts`) — isolated Git worktrees per task
- **Task Queue** — active/blocked/completed with persistence
- **Worker Agents** — specialized (coder, debugger, reviewer, etc.)

### 3. Claude Code (`~/.claude/`)
- **Agents**: 26 specialized agents in `agents/`
- **Skills**: 67 skills in `skills/` (graphify, ads, trading, etc.)
- **Session Storage**: `projects/` — JSONL per session (400KB–48MB each)
- **History**: `history.jsonl` — 453 entries
- **Hooks**: Auto-heal, task-judge, memory-index-guard, save-task-context, AST-check
- **Model Switcher**: `models-switcher.sh` for manual routing

### 4. Context System (`~/.context/`) — FROM PREVIOUS SESSION
- **Pipeline**: import → normalize → clean → extract → index
- **Archive**: 50 sessions imported (28 Claude, 5 Hermes, 1 Graphify, 1 Deepseek, 2 Shell)
- **Knowledge**: 10 files (PROJECT.md, ARCHITECTURE.md, DECISIONS.md, TASKS.md, FAILURES.md, MODELS.md, PROVIDERS.md, DISCOVERIES.md, CURRENT_STATE.md, ROADMAP.md)
- **Search**: SQLite FTS5 indexer
- **OpenCode Integration**: Session start/end hooks

### 5. Graphify (`~/.graphify/`) — Knowledge Graph
- `global-graph.json` — 1.2MB persistent graph

---

## GitHub Integration Status
- **Authenticated**: Yes (gh CLI + keyring)
- **Protocol**: HTTPS with gh credential helper
- **Remotes**: All 3 repos have GitHub origins
- **Worktrees**: deepseek-harness has 7 active worktrees; trading-bot has empty worktrees dir

---

## Reusable Components (High Value)

| Component | Location | Reuse Strategy |
|-----------|----------|----------------|
| **Workspace CLI** | `~/.hermes/universal-workspace/packages/cli/main.py` | **EXTEND** — already has repos, sync, task, plan, doctor, conversational |
| **Model Router** | `~/.deepseek-harness/.task/model-router.ts` | **INTEGRATE** — free-only, failover, circuit breakers, role-based |
| **Worktree Manager** | `~/.deepseek-harness/.task/worktree-manager.ts` | **INTEGRATE** — isolated worktrees per task |
| **Task Queue** | `~/.deepseek-harness/.task/task-queue.ts` | **EXTEND** — persistence, dependencies, agents |
| **Kanban** | `~/.hermes/kanban.db` | **INTEGRATE** — visual task boards |
| **Context Pipeline** | `~/.context/core/pipeline.py` | **EXTEND** — session archive, knowledge extraction, search |
| **OpenCode Integration** | `~/.context/core/opencode_integration.py` | **INTEGRATE** — session lifecycle hooks |
| **Secret Scanner** | `~/.context/core/secrets.py` + Hermes tirith | **INTEGRATE** — pre-commit/push scanning |
| **Git Correlator** | `~/.context/core/git_correlator.py` | **INTEGRATE** — session ↔ commit correlation |
| **Search Indexer** | `~/.context/core/indexer.py` | **INTEGRATE** — FTS5 across sessions, code, Git |

---

## Conflicts & Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Duplicate Task Systems** | Hermes kanban + deepseek .task + context tasks | Unify under single task registry with Kanban as UI, deepseek as engine |
| **Duplicate Session Stores** | Hermes state.db + Claude JSONL + context archive | Context archive as immutable raw; Hermes/Claude as live sources |
| **Model Routing Conflicts** | Hermes config (NVIDIA) vs deepseek router (free NVIDIA via OpenCode) | Use deepseek router as canonical; Hermes config as fallback |
| **Worktree Conflicts** | deepseek worktree-manager + trading-bot worktrees | Single worktree manager per repo; shared registry |
| **CLI Name Collision** | `workspace` exists in Hermes universal-workspace | Extend existing `workspace` CLI — least disruptive |
| **Secret Exposure** | Trading-bot .env has Binance keys; sessions may contain keys | Pre-commit secret scanning; redaction in archive |

---

## Proposed Integration Architecture

```
workspace (CLI)                    ← EXTEND Hermes universal-workspace CLI
├── repos                          ← EXISTING (sync, list, open)
├── task <desc>                    ← EXTEND (create cross-repo task graph)
├── plan <task>                    ← INTEGRATE deepseek master-agent
├── build                          ← NEW (spawn agents in isolated worktrees)
├── test                           ← NEW (run tests in worktree)
├── review                         ← NEW (code review agent)
├── fix                            ← NEW (debug agent + CI logs)
├── merge                          ← NEW (safe merge pipeline)
├── deploy                         ← NEW (deployment gates)
├── status                         ← EXTEND (live dashboard)
├── doctor                         ← EXTEND (full health checks)
├── search "<query>"               ← INTEGRATE context indexer + GitHub search
├── context                        ← INTEGRATE context pipeline
├── resume                         ← INTEGRATE checkpoint recovery
└── checkpoint                     ← NEW (persistent state snapshots)

CORE STATE (JSON/SQLite in ~/.hermes/universal-workspace/)
├── registry.json          — repos, tasks, agents, dependencies
├── checkpoints/           — task/Git/agent/model state snapshots
├── tasks/                 — task definitions + dependency graphs
├── agents/                — agent configs, assignments, state
└── logs/                  — structured operation logs

MODEL ROUTING              ← deepseek-harness ModelRouter (TypeScript → Python bridge)
├── THINKING: Nemotron 3 Ultra (planning, architecture)
├── EXECUTION: Nemotron 3.5 Lightning / DeepSeek V4 Flash (coding)
├── AUDIT: Nemotron 3 Ultra (review)
└── Failover: automatic with cooldown + exponential backoff

WORKTREE ISOLATION         ← deepseek worktree-manager
├── Per-task worktrees
├── Registry tracking
├── Cleanup on completion

SESSION ARCHIVE            ← context pipeline
├── Raw (immutable)
├── Normalized (canonical)
├── Cleaned (deduped)
├── Knowledge (extracted)
└── Index (FTS5 search)
```

---

## Implementation Order (Per Spec)

1. **Phase 1** ✅ — Audit complete (this document)
2. **Phase 2** — Architecture mapping (done above)
3. **Phase 3** — Core state (registry, tasks, checkpoints, events)
4. **Phase 4** — Git/GitHub (repo discovery, sync, branches, worktrees, PRs, CI)
5. **Phase 5** — OpenCode integration (reuse existing hooks, agents)
6. **Phase 6** — Model routing (bridge deepseek TS router → Python)
7. **Phase 7** — Agents (planner, coder, debugger, reviewer, test analyst)
8. **Phase 8** — Context (repo context, global context, retrieval, search)
9. **Phase 9** — Safety (secret scanning, merge gates, deployment gates, policies)
10. **Phase 10** — CLI (expose all via `workspace`)
11. **Phase 11** — Recovery (terminal restart, agent crash, model failure, etc.)
12. **Phase 12** — E2E test (safe test repo, full workflow)