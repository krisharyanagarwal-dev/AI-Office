# Office OS - User-Based Agent Orchestrator

Lightweight, automated agent office running on free models. **Zero Claude tokens. No installs.** Uses Python stdlib + tmux already on your machine.

## User-Based Architecture

Each user has their own isolated task space:
- Users log in via the web UI at `http://localhost:8083`
- Each user sees only their own tasks and results
- Task creation is tagged with the user who created it
- Cross-user task access is blocked (404 if you try to view another user's task)

### Default Users

| User | Name | Role |
|------|------|------|
| `aryan` | Aryan Agarwal | owner |
| `demo` | Demo User | user |

Add more users in `config/users.json`.

---

## Office UI (choose one)

| UI | Command | Best for |
|----|---------|----------|
| **Dashboard TUI** | `python3 ui/office_dashboard.py [user]` | Daily terminal use |
| **Tmux Office** | `bash office.sh [user]` | 4-pane tmux office |
| **Localhost Web** | `bash office.sh --web` | Browser at `http://localhost:8083` (login required) |
| **Quick status** | `python3 cli.py status` | One-line health check |
| **View result** | `python3 ui/view_result.py <task_id> [user_id]` | Full task output |

---

## Start everything

```bash
# Start orchestrator + tmux office as user 'aryan'
bash office.sh aryan

# Start as demo user
bash office.sh --user demo

# Orchestrator only (background)
bash office.sh --no-ui

# Localhost web server (login required)
bash office.sh --web
# Open: http://localhost:8083
# Login as: aryan or demo

# Everything (orchestrator + web + tmux)
bash office.sh --all --user aryan
```

Tmux navigation:
- `Ctrl+b n` — next window
- `Ctrl+b p` — previous window
- `Ctrl+b o` — switch panes
- `Ctrl+b d` — detach

## Localhost Web UI

Open `http://localhost:8083` in any browser:

1. **Login** — enter `aryan` or `demo`
2. **Dashboard** — see your provider pools, task board, latest results
3. **Create task** — form to submit tasks (title, description, agent, priority)
4. **Task detail** — `http://localhost:8083/task/<task_id>` shows full result
5. **Sign out** — top right link

Each user sees only their own tasks. Cross-user access returns 404.

---

## Provider Pools (all free)

| Pool | Models | Tier |
|------|--------|------|
| nvidia_key1 | Nemotron 3 Ultra 550B, DeepSeek v4.1 Flash | pro |
| nvidia_key2 | Mistral Large 4 1T, Nemotron 3.5 Lightning | pro |
| nvidia_key3 | Nemotron 3.5 Lightning 30B, Nemotron Nano Omni 30B | general + lite |
| nvidia_key4 | DeepSeek v4.1 Flash, Nemotron 3 Ultra 550B | general + lite |
| google | Gemini 3.6 Flash, 3.5 Flash, 3.5 Flash Lite | general |
| openrouter | Nemotron 3.5 Lightning free, Nemotron 3 Ultra free | lite |

## Commands

```bash
# Start everything as user 'aryan'
bash office.sh aryan

# Start web server
bash office.sh --web

# Check status
python3 cli.py status
python3 cli.py list-tasks --user aryan
python3 cli.py providers
python3 cli.py users

# Create a task as a specific user
python3 cli.py task "Title" "Description" agent_id priority user_id

# View a task result (user-specific)
python3 ui/view_result.py <task_id> [user_id]

# Open dashboard as specific user
python3 ui/office_dashboard.py aryan

# Start web server
python3 core/web_server.py   # http://localhost:8083
```

## Architecture

```
┌─────────────────┐
│   GOD Agent     │  (michael) - orchestrates, assigns, escalates
│  (god_agent.py) │
└─────────┬───────┘
          │ assigns tasks (tagged with user_id)
┌─────────▼───────┐
│   Workers       │  (worker_agent.py) - execute via direct provider API
│  6 agents       │  principal-architect, software-architect, etc.
└─────────┬───────┘
          │ dispatches to
┌─────────▼───────┐
│  Provider API   │  Direct OpenAI-compatible API calls (no OpenCode CLI
│  (direct calls) │   overhead - ~3K input tokens vs ~53K)
│  230 subagents  │  each pinned to a free model
└─────────┬───────┘
          │ routes through
┌─────────▼───────┐
│ Provider Router │  Round-robin across pools with rate-limit cooldowns
│  (router.py)    │  Task counts persisted to disk; per-tier routing
└─────────┬───────┘
          │
    ┌─────┴─────┬─────┬─────┬─────┬─────┐
  NVIDIA×4   Google  OpenRouter  Groq(fallback)
  (credit)   (free)   (free)     (free)
```

## UI Files

```
ui/office_dashboard.py   - Full-screen terminal office UI (user-aware)
ui/tmux_office.sh        - 4-pane tmux office layout (user-aware)
ui/view_result.py        - View full task result (user-specific)
core/web_server.py       - Localhost web server with login (port 8083)
office.sh                - Start everything (orchestrator + web + tmux)
core/hive.py             # User-isolated task/mailbox/memory store
core/router.py           # Provider round-robin + cooldowns (persisted)
agents/god_agent.py      # Michael - GOD orchestrator (tags tasks with user_id)
agents/worker_agent.py   # Workers execute via direct provider API calls
cli.py                   # CLI task management (--user flag)
config/users.json        # User definitions + sessions
config/office.json       # Provider pools & tiers
config/router_state.json # Persisted round-robin task counts
config/com.aryan.office-os.plist        # Launchd: orchestrator
config/com.aryan.office-os-web.plist  # Launchd: web server
```

## Memory Constraints

Designed for 16 GB machines:
- No Electron (unlike Munder Difflin desktop app)
- Pure Python stdlib, ~50 MB RAM
- ThreadPoolExecutor for concurrent tasks
- JSON file-based state (no database)
- 4-6 concurrent workers max

## Free Model Strategy

- **Zero Claude tokens** - all providers are free
- NVIDIA ×4 keys = 4 independent credit pools
- Google Gemini free tier
- OpenRouter free models as fallback
- Groq declared but not used as primary (rate limits under burst)
- Round-robin within pools, failover across pools on rate limits

## Reboot Persistence

To auto-start on reboot, copy the launchd plists:

```bash
cp config/com.aryan.office-os.plist ~/Library/LaunchAgents/
cp config/com.aryan.office-os-web.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.aryan.office-os.plist
launchctl load ~/Library/LaunchAgents/com.aryan.office-os-web.plist
```

Both use `KeepAlive: true` so they restart automatically if they crash.

## Key Safety Features

- **Lockfile**: Prevents double-running of orchestrator/web server
- **Rate-limit detection**: Provider pools are cooled down on 429/quota errors
- **Daily quota**: Providers exhausting daily quota are cooled down until midnight
- **Timeout handling**: curl timeouts (exit 28) trigger pool cooldown
- **Per-priority timeouts**: low=120s, normal=180s, high=300s
- **Reasoning stripping**: Removes model thinking blocks from responses
- **Atomic writes**: All JSON writes use temp-file + rename to prevent corruption
- **Corrupt file guard**: Corrupt JSON files return None instead of crashing

## Proven Results (7/8 tasks completed on free models)

- Security audit checklist (13 sections, 100+ checks)
- Cloud cost optimization (25-40% savings analysis)
- API documentation template
- Meeting notes system (4-section format)
- Microservices architecture design
- Python hello world script
- API rate limiter design (Redis, token bucket vs sliding window)