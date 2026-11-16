# PROJECT MEMORY

> **Recovered from OpenCode SQLite database** (~/.local/share/opencode/opencode.db)  
> **Sessions found:** 63,799 | **Date range:** 2026-08-30 → 2026-09-24  
> **Storage format:** SQLite (session, message, part, project tables)  
> **Recovery:** PARTIAL — full conversation content recovered for key sessions; metadata for all

---

## 1. CURRENT SYSTEM

| Component | Status | Notes |
|-----------|--------|-------|
| **OpenCode** | Active | v1.18.32, NVIDIA Nemotron 3 Ultra model |
| **Primary Workspace** | `/Users/aryanagarwal` | Global project |
| **Active Projects** | 8 | global, openalice-fleet, deepseek-harness, polymarket, trading-bot, munder-difflin, wifi_security_bot, nano_alice |
| **Key Skills Loaded** | 100+ | ads-*, crypto-*, trading-*, india-*, project-memory, orchestrate, graphify, etc. |

---

## 2. HISTORICAL TIMELINE

| Date | Session | Project | Work Summary | Outcome |
|------|---------|---------|--------------|---------|
| 2026-08-30 | ses_fabb21d9cffe2U75SHddSmZEJN | deepseek-harness | **NVIDIA Nemotron role-based routing implemented** — MASTER (Nemotron 3 Ultra) for planning/architecture, WORKER (Nemotron 3.5 Lightning) for implementation, escalation after 2 WORKER failures, fallback to Nemotron 3 Super. Added to cordis.patch.yml bundle. | ✅ 23/23 tests pass, build succeeds |
| 2026-08-30 | ses_fad5a778dffe962fvg5sU87lnm | wifi_security_bot | Fixed 200+ `datetime.utcnow()` deprecation warnings, syntax error in core/reporting (f-string), pytest collection warning. | ✅ 100 tests pass, zero warnings |
| 2026-09-01 | ses_fa1b4efd4ffemQxdJFKjLweiGP | openalice-fleet | **Free Harness / Anthropic Bridge debugging** — Bridge to NVIDIA NIM working for ~4 requests, then Free Harness rate limits (500 errors). nim wrapper reliable. | ✅ Bridge works for few requests; ⚠️ Free Harness rate limit ~4 req |
| 2026-09-08 | ses_f7fb834cfffeoZw7dteWmqerD4 | openalice-fleet | **Removed moonshotai/kimi-k3 from Free Harness** — Cleaned all references (model list, routing logic, payload prep, timeout logic) across free_harness.py. | ✅ All kimi-k3 references removed |
| 2026-09-11 | ses_f6f757a92ffeziHyQkjMqHzhpS / ses_f6b312ddbffefbMudT6TgAMkRQ | global | Heavy NVIDIA Nemotron usage — extended multi-turn build sessions with high token counts (100k+ tokens). | ✅ Ongoing build work |
| 2026-09-12 | ses_f4a2be2ebffeQSGvAaqFbEVxMJ | polymarket | **Paper trading profitability engine audit** — Forensic audit completed: model immutability, adaptive thresholds, real P&L, control groups, market scanner, data boundaries, execution assumptions, profitability gate, dry-run requirement, LLM lineage, Kelly safety, paper-only gate. | ✅ Audit complete; ⚠️ BLOCKED — no live market data |
| 2026-09-19 | ses_f42bbd808ffeUZxwAM0lRfpUT0 | global | **Office renderer UI components** — Created office start command, MasterAgent lifecycle, terminal inventory, task history, code visualization architecture. | ✅ Office components created |
| 2026-09-19 | ses_f446b3eafffeMP1H6dcetyE10N | global | High-performance code visualization architecture. | ✅ Architecture designed |
| 2026-09-19 | ses_f44832765fferih2XGqFpBsHJ1 | global | Unified terminal inventory and task history. | ✅ Inventory system built |
| 2026-09-20 | ses_f4a2be2ebffeQSGvAaqFbEVxMJ | global | **Continue openalice paper trading pipeline** — Continued polymarket engine work. | 🔄 In progress |
| 2026-09-20 | ses_f4a911807ffe5dA344BqUfGHSJ | global | **Stale-task lifecycle & watchdog recovery harnesses** — Built recovery system for agent fleet. | ✅ Watchdog implemented |
| 2026-09-24 | ses_f307ee96cffevjl90KaiWw718R | global | **Mac mini setup** — Diagnosed Mac mini (as-mac-mini.local, user `a`) unreachable on 192.168.29.0/24. Previous IP 192.168.29.202 offline. SSH port 22 closed on all responsive hosts. | ⚠️ Physical access required to power on + enable Remote Login |
| 2026-09-24 | ses_f305c9e96ffez0kt70E9j1svqd | global | **Merge all sessions into one** — Current session: history recovery & consolidation. | 🔄 In progress |

---

## 3. OPENALICE

### OpenAlice Fleet (`/Users/aryanagarwal/openalice-fleet`)
- **Free Harness** (`services/free_harness.py`): Multi-provider LLM router (NVIDIA, Groq, OpenRouter, Cerebras, SambaNova, etc.) with circuit breakers, fallback chains, streaming support.
- **Anthropic Bridge** (`services/anthropic_bridge.py`): Proxies Anthropic-format requests to Free Harness. Works for ~4 requests then hits Free Harness rate limit (500 errors).
- **NVIDIA NIM Models**: `nvidia/nemotron-3-ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/nemotron-3.5-lightning-30b-a3b`
- **Removed**: `moonshotai/kimi-k3` (was vision model, no longer on free tier)
- **nim wrapper** (`~/bin/nim`): Reliable CLI access to NVIDIA NIM via bridge

### Key Files
| File | Purpose |
|------|---------|
| `services/free_harness.py` | Core multi-provider LLM router with circuit breakers |
| `services/anthropic_bridge.py` | Anthropic API → Free Harness proxy (port 19593) |
| `services/pm_agent_llm.py` | Fleet LLM client for pm-agent with per-agent overrides |
| `~/.zshrc` | Exports ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_MODEL |

---

## 4. TRADING / PAPER TRADING

### Polymarket Profitability Engine (`/Users/aryanagarwal/Documents/polymarket/research/`)
- **Engine**: `profitability_engine_fixed.py` — Paper-only, probabilistic edge discovery
- **Audit Status**: ✅ **COMPLETE** (FINAL_AUDIT_SUMMARY.md)
- **Gate Status**: **BLOCKED** — No live Polymarket API connection
- **Key Fixes Implemented**:
  1. Model immutability (FROZEN/CANDIDATE/VALIDATION/RETIRED states)
  2. Adaptive threshold safety (THRESHOLD_LEARNER separate from ACTIVE_MODEL)
  3. Real P&L framework (`pnl = payout - entry_cost - fees - slippage`)
  4. Control groups: RANDOM, MARKET_BASELINE, BASE_RATE
  5. Real market data connection attempt with proper error handling
  6. Data boundary compliance (no synthetic/unavailable data)
  7. Execution assumptions frozen (`execution_assumptions.json`)
  8. Profitability gate tracking (`profitability_gate.json`)
  9. Dry-run requirement (`dry_run_test.py`)
  10. LLM provider lineage tracking
  11. Kelly safety with hard caps
  12. Paper-only safety gate (REAL_ORDER_SUBMISSION_ALLOWED = FALSE)

### Polymarket Agent (`/Users/aryanagarwal/Documents/polymarket/`)
- `pm_agent_llm.py` — Fleet LLM client with per-agent provider overrides
- `.agent_llm.json` — Provider config with fallback chain (ollama floor)
- `llm_client.py` — Base HTTP client with env var resolution

---

## 5. NVIDIA / NEMOTRON

### DeepSeek Harness Integration (`/Users/aryanagarwal/deepseek-harness/`)
- **Role-based Model Router** (`packages/llm/llm-router/`):
  - **MASTER**: `nvidia/nemotron-3-ultra-550b-a55b` — planning, architecture, debugging
  - **WORKER**: `nvidia/nemotron-3.5-lightning-30b-a3b` — implementation, coding, tests
  - **FALLBACK**: `nvidia/nemotron-3-super-120b-a12b`
  - Auto role detection from request `purpose` + context keywords
  - WORKER retry with checkpoint preservation (2 retries)
  - Escalation to MASTER after 2 WORKER failures
  - NVIDIA-only provider (no OpenRouter, no paid models)
- **Bundle Config** (`packages/bundle/base/cordis.patch.yml`): llm-router + llm-pi-ai (NVIDIA provider)

### Free Harness Models
- Primary: `nvidia/nemotron-3-super-120b-a12b`
- Heavy usage in recent sessions (100k+ token contexts)

---

## 6. FREE HARNESS

### Architecture
```
Claude Code → Anthropic Bridge (19593) → Free Harness (8080) → NVIDIA NIM
                          ↓
                    nim wrapper (reliable)
```

### Provider Chain (priority order)
1. **nvidia** — NVIDIA NIM (integrate.api.nvidia.com/v1)
2. **groq** — GroqCloud
3. **openrouter** — OpenRouter (z-ai, meta-llama, google, mistralai)
4. **cerebras** — Cerebras
5. **sambanova** — SambaNova
6. **fireworks** — Fireworks AI
7. **deepinfra** — DeepInfra
8. **ollama** — Local fallback (always last)

### Circuit Breakers
- Per-provider failure tracking
- Automatic fallback on 401/429/5xx/network error
- Logging every fallback to stderr

### Known Issue
- **Free Harness rate limit**: ~4 requests before 500 errors
- **Workaround**: Use `nim` wrapper for reliable access

---

## 7. OFFICE / AGENT FLEET

### Office System (`/Users/aryanagarwal/`)
- **MasterAgent**: Central orchestrator for agent fleet
- **Office renderer UI**: Terminal inventory, task history, code visualization
- **Stale-task lifecycle**: Watchdog recovery for stuck agents
- **Command Center**: `packages/support/command-center/` (hermes-reader adapter)
- **Session persistence**: JSONL-based session log export

### Key Components
| Component | Location | Status |
|-----------|----------|--------|
| MasterAgent | global project | Active |
| Office start command | global | Fixed |
| Terminal inventory | global | Built |
| Task history | global | Built |
| Code visualization | global | Architecture designed |
| Watchdog recovery | global | Implemented |

---

## 8. MAC MINI

### Target Machine
- **Hostname**: `as-mac-mini.local`
- **Username**: `a`
- **Previous IP**: `192.168.29.202` (now offline/incomplete ARP)
- **Expected Interface**: Wi-Fi (en0) or Ethernet (en1)

### Current Network (MacBook Air)
- **IP**: `192.168.29.102` (en0/Wi-Fi)
- **Gateway**: `192.168.29.1`
- **Active IPs on subnet**: 1 (router), 31 (Apple MAC), 102 (MacBook), 136, 170
- **SSH Port 22**: Closed/filtered on all responsive hosts
- **Bonjour**: `as-mac-mini.local` does not resolve

### Required Fix (Physical Access Needed)
1. Power on Mac mini
2. Enable **Remote Login** (System Settings → General → Sharing)
3. Verify same LAN connection (Wi-Fi or Ethernet to same router)
4. Check IP: `ipconfig getifaddr en0` or `en1`
5. Verify Bonjour: `dns-sd -Q as-mac-mini.local`

### SSH Command (Once Fixed)
```bash
ssh a@as-mac-mini.local
# or by IP
ssh a@192.168.29.XXX
```

---

## 9. IMPORTANT FILES

| File | Project | Description |
|------|---------|-------------|
| `~/.local/share/opencode/opencode.db` | All | SQLite session database (7 GB) |
| `openalice-fleet/services/free_harness.py` | OpenAlice | Multi-provider LLM router |
| `openalice-fleet/services/anthropic_bridge.py` | OpenAlice | Anthropic→Free Harness proxy |
| `deepseek-harness/packages/llm/llm-router/src/index.ts` | Nemotron | Role-based router (MASTER/WORKER) |
| `deepseek-harness/packages/bundle/base/cordis.patch.yml` | Nemotron | Bundle config with NVIDIA models |
| `polymarket/research/FINAL_AUDIT_SUMMARY.md` | Trading | Forensic audit results |
| `polymarket/research/profitability_engine_fixed.py` | Trading | Paper trading engine |
| `polymarket/pm_agent_llm.py` | Trading | Fleet LLM client |
| `wifi_security_bot/` | WiFi Sec | 100 tests passing, clean |
| `~/bin/nim` | OpenAlice | Reliable NVIDIA NIM CLI wrapper |
| `~/.zshrc` | Config | ANTHROPIC_* exports for bridge |

---

## 10. DECISIONS

| Decision | Context | Rationale |
|----------|---------|-----------|
| **NVIDIA-only for Nemotron routing** | DeepSeek Harness | No paid providers; Nemotron 3 Ultra/Super/Lightning free on NVIDIA NIM |
| **Role-based routing (MASTER/WORKER)** | DeepSeek Harness | Separate planning from implementation; escalation on failure |
| **Free Harness as primary LLM router** | OpenAlice | Free tier multi-provider with fallback; no API keys needed for most |
| **Anthropic Bridge for Claude Code compat** | OpenAlice | Allows Claude Code to use Free Harness via ANTHROPIC_BASE_URL |
| **Paper-only trading** | Polymarket | Safety: no real money, strict data boundaries, control groups |
| **Model immutability (FROZEN state)** | Polymarket | Prevents overfitting; improvements create new versions |
| **Dry-run mandatory before paper trading** | Polymarket | Validates signal quality without executing trades |
| **Kelly fractional with hard caps** | Polymarket | Prevents blowup; position size decreases with uncertainty |
| **nim wrapper over Claude Code** | OpenAlice | Free Harness rate limit (~4 req) makes Claude Code unreliable |

---

## 11. FAILED ATTEMPTS

| Attempt | Issue | Resolution |
|---------|-------|------------|
| **Claude Code via Bridge** | Free Harness rate limit (~4 req) → 500 errors | Use `nim` wrapper instead |
| **moonshotai/kimi-k3 in Free Harness** | Not on free tier; vision model | Removed all references |
| **Mac mini SSH via .local** | mDNS not resolving; machine offline | Physical access required |
| **Mac mini SSH via 192.168.29.202** | IP offline (incomplete ARP) | Machine likely asleep/off |
| **Mac mini SSH via 192.168.29.31/136/170** | Port 22 closed/filtered | Not the Mac mini or SSH disabled |
| **Polymarket live API connection** | Environment blocks Polymarket API | Engine BLOCKED until resolved |
| **WiFi Security Bot syntax error** | f-string nested ternary `{'exceeded' if ...}` | Refactored to variable + simple f-string |

---

## 12. CURRENT BLOCKERS

1. **Mac mini unreachable** — Requires physical access to power on + enable Remote Login
2. **Polymarket live data** — API not accessible from current environment; engine BLOCKED
3. **Free Harness rate limit** — ~4 requests before 500; limits Claude Code reliability
4. **NVIDIA API timeouts** — 5-min timeout on integrate.api.nvidia.com (seen in recent sessions)

---

## 13. NEXT ACTIONS

| Priority | Action | Project | Notes |
|----------|--------|---------|-------|
| 1 | **Physically access Mac mini** → power on, enable Remote Login, verify IP | Mac Mini | Prerequisite for fleet deployment |
| 2 | **Resolve Polymarket API access** | Trading | Unblocks paper trading engine |
| 3 | **Deploy agent fleet to Mac mini** | Office/Fleet | Once Mac mini online |
| 4 | **Extend paper trading dry-run validation** | Trading | Run dry_run_test.py for extended period |
| 5 | **Monitor NVIDIA API reliability** | All | Recent 5-min timeouts on integrate.api.nvidia.com |

---

## 14. RECOVERED SESSION INDEX

| Date | Session ID | Project | Topic | Summary |
|------|------------|---------|-------|---------|
| 2026-08-30 | ses_fabb21d9cffe2U75SHddSmZEJN | deepseek-harness | Nemotron role-based routing | MASTER/WORKER/FALLBACK with escalation; 23 tests pass |
| 2026-08-30 | ses_fad5a778dffe962fvg5sU87lnm | wifi_security_bot | Lint/syntax fix | 100 tests pass, zero warnings |
| 2026-09-01 | ses_fa1b4efd4ffemQxdJFKjLweiGP | openalice-fleet | Free Harness bridge debug | Bridge works ~4 req; nim wrapper reliable |
| 2026-09-08 | ses_f7fb834cfffeoZw7dteWmqerD4 | openalice-fleet | Remove kimi-k3 | All references cleaned from free_harness.py |
| 2026-09-11 | ses_f6f757a92ffeziHyQkjMqHzhpS | global | Heavy Nemotron build | Extended multi-turn, 100k+ tokens |
| 2026-09-12 | ses_f4a2be2ebffeQSGvAaqFbEVxMJ | polymarket | Paper trading audit | Audit complete; BLOCKED (no live data) |
| 2026-09-19 | ses_f42bbd808ffeUZxwAM0lRfpUT0 | global | Office renderer UI | MasterAgent, terminal inventory, task history |
| 2026-09-19 | ses_f446b3eafffeMP1H6dcetyE10N | global | Code visualization arch | High-performance architecture |
| 2026-09-19 | ses_f44832765fferih2XGqFpBsHJ1 | global | Terminal inventory | Unified inventory system |
| 2026-09-20 | ses_f4a911807ffe5dA344BqUfGHSJ | global | Stale-task watchdog | Recovery harnesses for agent fleet |
| 2026-09-24 | ses_f307ee96cffevjl90KaiWw718R | global | Mac mini setup | Diagnosed offline; physical access needed |
| 2026-09-24 | ses_f305c9e96ffez0kt70E9j1svqd | global | Session merge | Current: history recovery & consolidation |

---

## 15. FUTURE OPENCODE SESSIONS — AUTO-LOAD MECHANISM

### Verified Mechanism: `project-memory` Skill
```bash
/skill project-memory
```
- Maintains living project brain (decisions, state, next steps)
- Saves to project memory file on session end
- Loads on session start for continuity

### OpenCode Native Support
- **`--continue`** flag: Resumes last session by ID
- **`--session <id>`**: Continues specific session
- **`opencode export <sessionID>`** / **`opencode import <file>`**: Manual backup/restore
- **Config**: `~/.config/opencode/opencode.json` (settings only, not history)

### Recommended Workflow
```bash
# At session start
/skill project-memory
# ... work ...
# At session end (auto-saves)
```

---

## 16. RECOVERY VERIFICATION

| Check | Result |
|-------|--------|
| **A. Session storage discovered** | ✅ SQLite at `~/.local/share/opencode/opencode.db` (7 GB) |
| **B. Sessions recovered** | ✅ 63,799 total; key sessions fully extracted |
| **C. Date range recovered** | ✅ 2026-08-30 → 2026-09-24 |
| **D. Full conversation recovery** | **PARTIAL** — Full message/part content for key sessions; metadata for all |
| **E. Unified memory created** | ✅ `PROJECT_MEMORY.md` at workspace root |
| **F. Exact location** | `/Users/aryanagarwal/PROJECT_MEMORY.md` |
| **G. Project-memory mechanism found** | ✅ Skill exists; verified loadable |
| **H. Auto-loading verified** | ✅ `/skill project-memory` works |
| **I. History not recovered** | Most of 63,799 sessions (low-value/test sessions); only high-cost sessions fully extracted |
| **J. Secrets redacted** | ✅ No API keys, tokens, or passwords in recovered data (stored as env var refs) |
| **K. Future workflow** | Use `/skill project-memory` at session start; `opencode export` for manual backup |

---

## 17. SECRETS REDACTION CONFIRMATION

All recovered data uses **environment variable references** for secrets:
- `NVIDIA_API_KEY` → resolved from `.env` (gitignored)
- `ANTHROPIC_API_KEY` → not in database
- `GROQ_API_KEY` → not in database
- `OPENROUTER_API_KEY` → not in database
- `.agent_llm.json` uses `env:VAR` syntax, resolved at runtime

**No plaintext secrets found in session database.**

---

## 18. TRADING DEPLOYMENT UPDATE — 2026-09-24

- Added `research/market_adapter.py` with health-checked Polymarket CLOB/Gamma and Oddpool failover; no source means no trading.
- Added `--data-source`, `--once`, `--scan-interval`, and default dry-run controls to `research/profitability_engine_fixed.py`.
- Added dedicated NVIDIA providers for 550B/120B/30B in `.agent_llm.json`; OpenRouter is not in the Nemotron chain.
- Added `deploy/com.aryan.pm-engine.plist`, `deploy/install-mini.sh`, `deploy/sync-mini.sh`, and `deploy/DEPLOYMENT.md`.
- Mac mini `192.168.29.202` is reachable as `a`; trading checkout is synced at `/Users/a/polymarket`; launchd job `com.aryan.pm-engine` is running in Oddpool paper mode (`--data-source oddpool --paper`).
- Mac mini has Python 3.9 with NumPy, pandas, requests, SciPy, and scikit-learn installed for the user.
- Polymarket CLOB and Gamma both time out from the mini; Oddpool is now the configured source. The latest scan fetched 47 NVIDIA and 49 Tesla markets (96 combined); 0 paper trades were submitted. Rejection observability now reports all 47 NVIDIA candidates blocked by `edge_below_threshold`.
- Added real yfinance historical evidence for NVDA, TSLA, AAPL, SPX/SPY, Nifty (^NSEI), Sensex (^BSESN), Reliance, and Tata Motors; yfinance returned real rows on the mini.
- LLM selftest confirms dedicated NVIDIA keys are accepted: 550B and 120B routes connected during the check; 30B timed out and one default probe returned 503.
- Adapter tests: 5 passed. Adapter mypy checks passed. Full engine mypy still reports pre-existing project errors.
- Paper execution smoke test passed. No live-order path exists; `REAL_ORDER_SUBMISSION_ALLOWED = False`.

---

*Generated: 2026-09-24 | Source: ~/.local/share/opencode/opencode.db | Recovery: Phase 1-5 complete*