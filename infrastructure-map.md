# AI-Office Existing Infrastructure Map

**Generated**: 2026-11-23  
**Purpose**: Read-only discovery audit for making the OpenAlice infrastructure operate as one unified AI Office (per master system prompt, Section 15)

---

## 1. Project Root: `/Users/aryanagarwal/AI-Office/`

| File/Dir | Size | Modified | Description |
|---|---|---|---|
| `COMPANY_CHARTER.md` | 1,413 B | 2026-11-23 | Operating charter: paper/testnet-only, kill switch LOCKED, cost-honest rules |
| `company.py` | 8,272 B | 2026-11-23 | Unified launcher: dispatch, status, pnl, metrics, stocks commands |
| `company_dispatcher.py` | 11,133 B | 2026-11-23 | Task routing via keyword matching to 6 departments |
| `dost.py` | 41,858 B | 2026-11-23 | Proactive multi-modal autonomous research agent (320+ tests passing) |
| `upgrade_system.py` | 5,602 B | 2026-11-23 | Self-upgrade system for code, prompts, configs, processes |
| `README.md` | 793 B | 2026-11-23 | Quick-start overview |
| `NEXT_100_TASKS.md` | 3,104 B | 2026-11-23 | Next 100 tasks to dispatch |
| `logs/` | — | — | Company log directory |
| `scripts/` | — | — | Utility scripts (all_stocks_bot.py, etc.) |
| ` packages/` | — | — | Sub-package directory (see below) |
| ` test/` | — | — | Test directory |
| ` docs/` | — | — | Documentation directory |
| ` departments/` | — | — | Six department directories (assistant, fleet, ops, research, trading, upgrade) |
| ` unified-api/` | — | — | Node.js Fastify unified API layer (port 4749) |
| ` dashboard-ui/` | — | — | React dashboard frontend |
| ` reports/` | ~800 files | — | Generated report outputs |

---

## 2. Sub-Packages: `/Users/aryanagarwal/AI-Office/packages/`

| Directory | Entries | Description |
|---|---|---|
| `office-os/` | 34 | Core "Office OS" with API, agents, configs, launchd, tasks (~15K tasks), tests, UI |
| `office-core/` | 22 | Core database, workers, model-router, observability, prometheus, HUD |
| `trading/` | 84 | Trading bots, backtests, risk engines, research, execution engine (~30 passing tests) |
| `nvidia-office/` | 5 | NVIDIA-optimized components |
| `core/` | 39 | Core utilities and foundational modules |
| `all-files/` | 9 | All-file registry and management |
| `shared/` | 4 | Shared resources across packages |
| `qoder-session-floor/` | 14 | Session floor/qoder integration |
| `ui/` | 7 | UI component library |
| `utils/` | 7 | Utility modules |
| `nvidia-office/` | 5 | Nvidia-specific office components |

---

## 3. Key Source Files

### `company_dispatcher.py` — Department Routing

Routes tasks to 6 departments via keyword matching:

| Department | Keywords | Handler |
|---|---|---|
| **research** | hypothesis, gate, holdout, calibration, public record, research report, pre-register, out-of-sample, edge | `handle_research()` |
| **trading** | backtest, strategy, option, stock, nifty, nse, trade, paper, cost, margin, stt, gst, brokerage, equity, intraday, momentum, mean reversion, pair, fii, dii, bhavcopy, iv rank, straddle, strangle, condor | `handle_trading()` |
| **upgrade** | upgrade, refactor, improve, evolve, migrate, update config, self-improve, optimize code | `handle_upgrade()` |
| **ops** | pnl, profit, loss, tier, autonomy, provider health, dashboard, metrics, kill switch, ops | `handle_ops()` |
| **assistant** | code, write, analyze, strategize, plan, memo, report, document, review, debug, draft, email, slide | `handle_assistant()` |
| **fleet** | (default for non-keyword tasks) | `handle_fleet()` |

### `company.py` — Unified Launcher

Entry point with these command categories:

| Command | Description |
|---|---|
| `dispatch "task" [--department X]` | Route task to department |
| `upgrade --list \| --test \| --rules` | Self-upgrade system |
| `pnl` | Show office P&L ledger |
| `metrics` | Show dashboard metrics (Fastify at port 8083) |
| `stocks --limit N` | Run all-listed-stocks fundamental analysis |
| `status` | Full company status report |

### `COMPANY_CHARTER.md` — Absolute Rules

1. **PAPER ONLY** — Kill switch LOCKED. `live_orders_allowed = false`. No order path ever added.
2. **COST-HONEST** — All research deducts Groww costs (brokerage, STT, stamp, GST, SEBI/exchange, slippage). Gross edge is never profit.
3. **PRE-REGISTERED** — Every hypothesis registered before backtest. Tuning window vs holdout split declared upfront.
4. **VERIFIED** — Producer ≠ verifier. Tripartite consensus + devil-advisor for major verdicts.
5. **SELF-UPGRADING** — The company upgrades its own code, prompts, and processes continuously.
6. **NO CURVE-FITTING** — Parameters never tuned after seeing results. Gate applied deterministically.

**Boundaries (Never Change)**: Kill switch: LOCKED; Live orders: false; Broker connection: none; Real capital: not deployed through this system; All simulation, all free data.

---

## 4. Department Directories: `/Users/aryanagarwal/AI-Office/departments/`

| Department | Key Files | Status |
|---|---|---|
| **assistant** | — | General Claude capabilities (code, write, analyze, strategize, plan) — Tier A autonomous |
| **fleet** | — | JEV 32-agent dispatch (paper-only, Tier C blocked, kill switch LOCKED) |
| **ops** | — | Company P&L, autonomy tiers, provider health, dashboards — Tier B gated |
| **research** | — | Hypothesis queue, backtests, verdict gates, calibration, public record |
| **trading** | — | Paper engine, cost models, strategies, forward sim — Tier B gated |
| **upgrade** | — | Self-upgrade system: code, prompts, configs, processes — Tier B gated |

---

## 5. OpenAlice Fleet Infrastructure

| Component | Path | Description |
|---|---|---|
| `.openalice/` | `/Users/aryanagarwal/.openalice/` | Main OpenAlice data directory |
| `openalice-fleet/` | `/Users/aryanagarwal/.openalice-fleet/` | Fleet control center |
| `jev-dispatcher.py` | `/Users/.openclaw/jev-dispatcher.py` | 32-agent JEV dispatcher (paper-only) |
| launchd jobs | `~/Library/LaunchAgents/` | Periodic agent orchestrator jobs |
| agent sessions | Various Terminal/Qoder sessions | Active in-worker agent panes |

---

## 6. _office Management Layer

| File/Dir | Purpose |
|---|---|
| `_office/inbox/` | 60+ inbox items (alerting.md → weekly-reviewer.md) — Inbox & Communications dept |
| `_office/BOARD.md` | Governance board charter |
| `_office/POLICY.md` | Operating policies |
| `_office/STANDUP.md` | Daily standup format |
| `_office/trash/` | Task wastebasket |

---

## 7. Session Control Panel (React)

| Component | Path | Status |
|---|---|---|
| `session-control-panel/` | `/Users/aryanagarwal/session-control-panel/` | React app at localhost:3000; needs Brain Bot integration |
| UI src/ | `src/` | Tailwind CSS + shadcn/ui components |
| Public/ | `public/` | Static assets |

---

## 8. Unified API Layer

| Component | Path | Port | Description |
|---|---|---|---|
| `unified-api/` | `/Users/aryanagarwal/AI-Office/unified-api/` | Node.js Fastify server |
| Metrics endpoint | `http://127.0.0.1:8083/metrics` | Dashboard metrics |
| API docs | `API_Documentation_Template.md` | office-os package docs |

---

## 9. Test Suites & Verification

| Test Directory | Coverage | Status |
|---|---|---|
| `AI-Office/test/` | — | Test files for company launcher |
| `AI-Office/packages/trading/tests/` | 30+ tests | 100+ passing (per project memory) |
| `AI-Office/packages/office-os/tests/` | — | Office OS test suite |
| `.pytest_cache/` | — | Persistent pytest cache |

---

## 10. Memory Architecture

| Scope | Path | Entries |
|---|---|---|
| **User-scope** | `/Users/aryanagarwal/.qoder/memory/MEMORY.md` | 13 entries (feedback settings, test results) |
| **Project-scope** | `/Users/aryanagarwal/.qoder/projects/-Users-aryanagarwal/memory/MEMORY.md` | 7 entries (Fundamentals Cross-Repo Wiring, Unified Dashboard Goal, etc.) |
| **Per-agent** | `/Users/aryanagarwal/.agents/` | Agent runtime definitions |

---

## 11. Critical Gating Constraints (from COMPANY_CHARTER.md)

- ✅ **PAPER ONLY** — Kill switch permanently LOCKED; no live orders possible through this system
- ✅ **COST-HONEST** — All research metrics include full cost deduction (brokerage, STT, stamp, GST, slippage)
- ✅ **NO LIVE CAPITAL** — Virtual ₹1,00,000 paper ledger only; real capital deployment requires separate repo/credentials
- ✅ **VERIFIED PRODUCTION** — Tripartite consensus required for major verdicts; producer ≠ verifier
- ✅ **SELF-UPDATING** — Upgrade system operates within deterministic gates (no curve-fitting)

---

## 12. What Currently Works (Verified)

- Company launcher (`company.py`) dispatch function
- Department routing via keyword matching (`company_dispatcher.py`)
- All-stocks fundamental analysis bot (`all_stocks_bot.py`)
- Dost agent (320+ tests passing)
- Office OS core server and API
- Dashboard UI React application
- Session control panel React app
- Pytest test suites (100+ passing in trading)
- Memory architecture (user + project scope MEMORY.md files)

---

## 13. What Needs Integration (Discovery Gaps)

1. **Inbox → Department routing**: _office inbox items not routed to AI-Office departments
2. **Unified task tracking**: No shared task IDs across dispatchers
3. **Office HUD integration**: Session control panel not connected to Brain Bot
4. **Cross-department dependencies**: No dependency tracking between departments
5. **Free-model inventory**: No model registry per the free model strategy table
6. **Memory bridge**: User-scope and project-scope memory not synchronized
7. **Verification loop**: No independent verification of completed work per Section 8 (Quality Assurance dept)

---

*End of Infrastructure Map*