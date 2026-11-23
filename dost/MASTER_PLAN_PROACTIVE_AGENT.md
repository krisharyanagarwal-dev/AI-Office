# Master Plan: Proactive Multi-Modal Autonomous Agent

## Vision
Dost becomes a **proactive research & operations partner** that:
- **Sees everything**: market data, fleet health, user patterns, comms
- **Acts before asked**: morning briefings, anomaly alerts, opportunity scans
- **Remembers forever**: cross-session memory across voice/web/CLI/Telegram
- **Improves itself**: writes skills, tests them, deploys to fleet
- **Speaks everywhere**: voice (Siri), web (dashboard), CLI, Telegram, Slack

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DOST CORE ORCHESTRATOR                     │
│  (chat_core.py + memory_pkg + proactive_scheduler)              │
└──────────────┬──────────────┬──────────────┬────────────────────┘
               │              │              │
      ┌────────▼─────┐ ┌─────▼──────┐ ┌────▼────────┐
      │  INTERFACES  │ │  MEMORY    │ │  SKILLS     │
      │              │ │            │ │             │
      │ • Voice/Siri │ │ • Sessions │ │ • Registry  │
      │ • Web/WS     │ │ • Facts    │ │ • Generator │
      │ • CLI        │ │ • Patterns │ │ • Tester    │
      │ • Telegram   │ │ • Vector   │ │ • Deployer  │
      │ • Slack/Email│ │   Store    │ │             │
      └──────────────┘ └────────────┘ └─────────────┘
               │              │              │
      ┌────────▼──────────────▼──────────────▼────┐
      │           FLEET ORCHESTRATION             │
      │  (dispatcher + 6 departments + jev)       │
      └───────────────────────────────────────────┘
```

---

## Phase 1: Universal Interface & Memory (Turns 1-15)

### 1.1 Voice Pipeline (Siri → STT → Chat → TTS → Siri)
- `dost/voice/stt.py` — Whisper.cpp/MLX local
- `dost/voice/tts.py` — Kokoro/MLX local
- `dost/voice/cli.py` — `python3 -m dost.voice "prompt"`
- `dost/siri_dost.sh` — Bridge to voice CLI
- **Test**: `test_voice_pipeline.py` STT→chat→TTS roundtrip

### 1.2 WebSocket Real-time Dashboard
- Upgrade `/dashboard` to WebSocket
- Push fleet metrics, task updates, alerts live
- `dost/web/ws_handler.py`

### 1.3 Telegram Bot (Proactive + Reactive)
- `dost/telegram/bot.py` — aiogram 3.x
- Commands: `/briefing`, `/status`, `/dispatch`, `/memory`
- Proactive: morning digest push, anomaly alerts
- **Test**: `test_telegram_bot.py`

### 1.4 Unified Memory Layer
- `dost/memory_pkg/unified.py` — Single API over:
  - `jarvis_memory/` (JSONL sessions)
  - Vector store (Chroma/FAISS) for semantic recall
  - Fact extraction (entities, preferences, decisions)
- **Test**: `test_unified_memory.py` — cross-interface recall

---

## Phase 2: Proactive Orchestration (Turns 16-30)

### 2.1 Morning Briefing Automation
- `dost/ops/morning_briefing.py` — 06:00 UTC cron
- Market scan → fleet dispatch → synthesize → push (Telegram/voice/web)
- Configurable topics via `office.json`

### 2.2 Anomaly Detection & Alerts
- `dost/ops/anomaly_watch.py` — Background loop (30s)
- Monitors: cost burn, pool saturation, error rates, drawdown
- Pushes to all interfaces with severity routing

### 2.3 Opportunity Scanner
- `dost/research/opportunity_scanner.py` — Hourly
- Screens: fundamentals, technicals, funding rates, governance
- Dispatches research tasks → synthesizes → presents top 3

### 2.4 Proactive Scheduler
- `dost/core/proactive_scheduler.py` — APScheduler
- Cron jobs + event-driven triggers
- Persists schedule in `office.json`

---

## Phase 3: Self-Improving Skills (Turns 31-45)

### 3.1 Skill Registry
- `dost/skills/registry.py` — JSON manifest: name, version, deps, tests
- Auto-discovers `dost/skills/*.py`

### 3.2 Skill Generator
- `dost/skills/generator.py` — LLM writes new skill from spec
- Template: interface, test, config, deploy
- Validates: syntax, imports, test passes

### 3.3 Skill Tester (Hermetic)
- `dost/skills/tester.py` — Spawns isolated test env
- Runs skill tests, captures coverage, reports
- **Test**: `test_skill_generator.py` — generates + tests a skill

### 3.4 Skill Deployer
- `dost/skills/deployer.py` — Validates → registers → hot-reloads
- Rollback on test regression

---

## Phase 4: Multi-Modal Polish (Turns 46-60)

### 4.1 Cross-Interface Session Sync
- Start on voice → continue on web → reply on Telegram
- Single `conversation_id` across all interfaces

### 4.2 Context-Aware Responses
- Memory injection: "Last week you asked about AAPL earnings..."
- Preference learning: terse vs verbose, channels, timing

### 4.3 Fleet Self-Healing
- Dost detects stuck tasks → restarts / re-dispatches
- Pool saturation → auto-failover → reports

### 4.4 Comprehensive Test Suite
- Integration: voice → memory → fleet → telegram
- Load: 100 concurrent sessions
- Chaos: kill dispatcher mid-task, verify recovery

---

## Success Criteria (All Verifiable)

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | Voice roundtrip < 3s | `test_voice_pipeline.py` |
| 2 | WebSocket pushes live metrics | `curl ws://localhost:8083/ws` |
| 3 | Telegram proactive push at 06:00 | Check chat history |
| 4 | Memory recall across interfaces | `test_unified_memory.py` |
| 5 | Morning briefing generates + pushes | `test_morning_briefing.py` |
| 6 | Anomaly detected → alert < 60s | `test_anomaly_watch.py` |
| 7 | Skill generated + tested + deployed | `test_skill_generator.py` |
| 8 | Cross-interface session continuity | Manual + integration test |

---

## Constraints (Non-Negotiable)

- **Paper/testnet only** — `live_orders_allowed=false` always
- **Kill switch LOCKED** — never touched
- **Advisory-only cost cap** — configurable, never halts
- **No key exposure** — presence-only, never read/print/copy
- **Forbidden paths untouched** — `.env`, `*.plist`, `*key*`, `*secret*`, `*token*`, `live_orders`, `order`, `executor`
- **Fail closed** — unverifiable = NOT-VERIFIED
- **No SEBI advice** — factual analysis only

---

## Current State (Turn 0)

| Component | Status |
|-----------|--------|
| CLI (6 depts) | ✅ Working |
| Fleet dispatch | ✅ Working |
| Web dashboard | ✅ Working |
| Doctor/health | ✅ Working |
| Voice scaffold | 🟡 Exists |
| Memory systems | 🟡 Exist (disconnected) |
| Telegram | 🟡 Scaffold only |
| Skills | 🟡 None |
| Proactive loops | 🟡 None |

---

## Next Action (Turn 1)

**Start Phase 1.1: Voice Pipeline TDD**
1. Create `test_voice_pipeline.py` with mocked STT/TTS
2. Implement `stt.py` (Whisper.cpp via subprocess)
3. Implement `tts.py` (Kokoro via MLX)
4. Wire `voice/cli.py` → `chat_core` → fleet dispatch
5. Update `siri_dost.sh` bridge
6. Verify: `siri_dost.sh "test"` → speaks response