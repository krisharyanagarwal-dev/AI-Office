# Office Core Architecture

## Overview

**office-core** is the central nervous system of the AI Office infrastructure. It provides a unified data layer, API gateway, agent orchestration, model routing, and launchd-based process management — all running on a two-machine topology (laptop + Mac mini).

---

## System Components

### 1. Database (`db.py`)
- **SQLite** (`~/AI-Office/packages/office-core/tasks.db`) with WAL mode for concurrent access
- **Tables**: `tasks`, `task_events`, `agents`, `model_routes`, `launchd_jobs`, `system_state`
- **JSONL append-only log** (`tasks.log`) for crash-safe event audit trail
- **Thread-local connections** for safe multi-threaded access

### 2. REST API (`workers/backend/api.py`)
- **FastAPI** on port 8080 (laptop)
- **Endpoints**:
  - `/tasks` — CRUD for task queue
  - `/agents` — Agent registry management
  - `/models` — Model router configuration
  - `/launchd` — Launchd job definitions
  - `/health` — Health check

### 3. Model Router
- **Configuration**: `model-router.yaml` (source of truth) + `model_routes` table (runtime)
- **Backends**: `mlx-local`, `nim-cloud`, `free-harness`, `ollama-local`
- **Routing rules**: Priority-based with fallbacks
- **Aliases**: Short names (`qwen`, `nemotron`, `llama3`) resolve to full model IDs
- **Health checks**: 60s interval, 3 consecutive failures = unhealthy
- **Rate limits**: Per-backend (requests/min + concurrent)

### 4. Launchd Manager (`scripts/generate_launchd.py`)
- **Source of truth**: `launchd_jobs` table in database
- **Generates** `.plist` files to `~/AI-Office/office-core/launchd/` (version-controlled)
- **Deploys** to `~/Library/LaunchAgents/` with `launchctl load -w`
- **Auto-sync** from agent registry: agents with `launchd_label` get jobs created automatically
- **Log paths**: `~/Library/Logs/{label}.log` / `{label}.err.log`

### 5. Workers
- **API worker**: Runs the FastAPI server (`workers/backend/api.py`)
- **Agent workers**: One per registered agent (llm, script, daemon, bridge, monitor)
- **Poll tasks** from database, execute, report results

### 6. HUD (Heads-Up Dashboard)
- **Port 4747** — Unified monitoring dashboard
- **Tracks**: API health, worker status, model router backends, launchd jobs
- **SSH tunnels** from laptop to Mini for Mini-hosted services

---

## Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Client    │────▶│  API :8080  │────▶│   Tasks DB  │◀───│  Workers (poll)  │
│  (CLI/HUD)  │     │  (FastAPI)  │     │  (SQLite)   │     │                  │
└─────────────┘     └─────────────┘     └─────────────┘     └────────┬─────────┘
                                                                      │
                                                                      ▼
                                                             ┌──────────────────┐
                                                             │  Model Router    │
                                                             │  (model-router)  │
                                                             └────────┬─────────┘
                                                                      │
                        ┌────────────────────────────────────────────┼────────────────────────────────────────────┐
                        ▼                                            ▼                                            ▼
               ┌───────────────┐                           ┌─────────────────┐                    ┌─────────────────┐
               │   mlx-local   │                           │   nim-cloud     │                    │  free-harness   │
               │  (Mini:11435) │                           │  (Mini:4200)    │                    │ (Laptop:19593)  │
               │  Qwen, Llama, │                           │  Nemotron 3.x   │                    │   Qwen Bridge   │
               │  Gemma, etc.  │                           │  VL, Nano, etc. │                    │                 │
               └───────────────┘                           └─────────────────┘                    └─────────────────┘
```

**Task Lifecycle**:
1. Client creates task via CLI/API/HUD → `tasks` table (`status=pending`)
2. Worker (assigned by `assignee` field) polls → claims task (`status=in_progress`)
3. Worker needs LLM → calls Model Router with alias (`qwen`, `nemotron`)
4. Router selects backend by priority/fallback → forwards to MLX/NIM/Free
5. Worker completes → updates task (`status=completed`/`failed`)
6. Event logged to `task_events` + JSONL log

---

## Deployment Topology

### Laptop (Development Machine)
| Component | Port | Description |
|-----------|------|-------------|
| office-core API | 8080 | FastAPI server |
| HUD Dashboard | 4747 | Monitoring UI |
| Free Harness Bridge | 19593 | Qwen9 bridge for free models |
| Launchd Agents | — | Local daemons (monitors, bridges) |

### Mac Mini (Inference Server)
| Component | Port | Description |
|-----------|------|-------------|
| MLX Server (Ollama Shim) | 11435 | Local MLX models (Qwen, Llama, Gemma) |
| NIM Proxy | 4200 | NVIDIA NIM endpoints (Nemotron family) |
| Ollama (disabled) | 11434 | Legacy, replaced by MLX shim |

### SSH Tunnels (Laptop → Mini)
```bash
# MLX via Ollama shim
ssh -L 11434:127.0.0.1:11434 -L 11435:127.0.0.1:11435 a@macmini

# NIM
ssh -L 4200:127.0.0.1:4200 a@macmini

# HUD access to Mini services
ssh -L 4747:127.0.0.1:4747 a@macmini
```

**Tunnel Management**: Persistent via `autossh` or launchd `KeepAlive`. All Mini endpoints accessed via `127.0.0.1:<port>` on laptop.

---

## Key Design Principles

1. **Single source of truth**: Database for runtime state, YAML for static config
2. **Launchd as process supervisor**: No systemd, no Docker — native macOS daemons
3. **Two-machine separation**: Laptop = control plane, Mini = data plane (GPU)
4. **Model router abstraction**: Workers never call backends directly
5. **Audit everything**: JSONL log + DB events for full traceability
6. **Health-first**: Every component exposes `/health`, monitored by HUD