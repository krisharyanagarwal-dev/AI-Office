# Agent Development Guide

## Agent Types

| Type | Description | Typical Use Case |
|------|-------------|------------------|
| `llm` | LLM-powered agent, calls Model Router | Reasoning, coding, analysis |
| `script` | Shell/Python script, no LLM | Data processing, ETL, sync |
| `daemon` | Long-running background process | Pollers, watchers, schedulers |
| `bridge` | Proxies requests to external service | API gateways, protocol adapters |
| `monitor` | Health/observability checker | Service uptime, metrics collection |

---

## Registration

### Via CLI
```bash
office-core agents create my-agent \
  --type llm \
  --model qwen \
  --tools "web_search,code_exec" \
  --launchd-label com.aryan.office-core.my-agent \
  --health-endpoint http://127.0.0.1:8081/health \
  --schedule "*/5 * * * *"
```

### Via API
```bash
curl -X POST http://127.0.0.1:8080/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "type": "llm",
    "model": "qwen",
    "tools": ["web_search", "code_exec"],
    "launchd_label": "com.aryan.office-core.my-agent",
    "health_endpoint": "http://127.0.0.1:8081/health",
    "schedule": "*/5 * * * *",
    "enabled": true
  }'
```

### Database Schema (`agents` table)
```sql
name TEXT PRIMARY KEY,
type TEXT NOT NULL,              -- llm, script, daemon, bridge, monitor
model TEXT,                      -- model alias (qwen, nemotron, etc.) or 'none'
tools TEXT,                      -- JSON array: ["web_search", "code_exec"]
policy TEXT,                     -- JSON: permissions, limits, timeouts
launchd_label TEXT,              -- e.g., com.aryan.office-core.my-agent
health_endpoint TEXT,            -- HTTP endpoint for /health
schedule TEXT,                   -- cron or interval (@daily, "*/5 * * * *")
enabled BOOLEAN DEFAULT 1,
metadata TEXT                    -- JSON blob for extensibility
```

---

## Launchd Integration

### Auto-Generation
When an agent has `launchd_label` set, run:
```bash
office-core launchd sync-agents   # Creates launchd_jobs entries from agents
office-core launchd generate --deploy  # Generates & installs plists
```

### Generated Plist Structure
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.aryan.office-core.my-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/aryanagarwal/AI-Office/office-core/agents/my-agent/run.py</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/aryanagarwal/AI-Office/office-core/agents/my-agent</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>StandardOutPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.my-agent.log</string>
    <key>StandardErrorPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.my-agent.err.log</string>
    <key>ProcessType</key><string>Background</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Minute</key><string>*/5</string>
    </dict>
</dict>
</plist>
```

### Program Path Convention
| Agent Type | Program Entry Point |
|------------|---------------------|
| `llm` | `agents/{name}/run.py` |
| `script` | `agents/{name}/run.sh` |
| `daemon` | `agents/{name}/daemon.py` |
| `bridge` | `agents/{name}/bridge.py` |
| `monitor` | `agents/{name}/monitor.py` |

---

## Model Access

Agents **never call backends directly**. Use the Model Router via aliases:

```python
# In your agent code
import requests

def call_model(prompt: str, model: str = "qwen") -> str:
    """Call Model Router with alias."""
    resp = requests.post(
        "http://127.0.0.1:8080/models/complete",  # Router endpoint
        json={"model": model, "prompt": prompt, "max_tokens": 4096},
        timeout=180
    )
    resp.raise_for_status()
    return resp.json()["completion"]
```

### Available Aliases (from `model-router.yaml`)
| Alias | Resolves To | Backend |
|-------|-------------|---------|
| `qwen` | `TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4` | mlx-local |
| `qwen3` | `qwen3:8b` | mlx-local |
| `qwen2.5` | `qwen2.5:7b` | mlx-local |
| `llama3` | `llama3.2:3b` | mlx-local |
| `nemotron` | `nvidia/nemotron-3.5-lightning-30b-a3b` | nim-cloud |
| `nemotron-ultra` | `nvidia/nemotron-3-ultra-550b-a55b` | nim-cloud |

### Fallback Behavior
1. Router tries primary backend for alias
2. On failure → tries fallback backend (defined in routing rules)
3. Final fallback → `free-harness` (qwen9 bridge)

---

## Health Endpoints

**Required** for HUD monitoring and launchd supervision.

### Implementation (FastAPI example)
```python
from fastapi import FastAPI
import psutil

app = FastAPI()

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "my-agent",
        "pid": psutil.Process().pid,
        "uptime_seconds": time.time() - START_TIME,
        "dependencies": {
            "model_router": check_router(),
            "database": check_db()
        }
    }

def check_router() -> dict:
    try:
        r = requests.get("http://127.0.0.1:8080/health", timeout=2)
        return {"status": "ok" if r.status_code == 200 else "degraded"}
    except Exception as e:
        return {"status": "down", "error": str(e)}
```

### HUD Integration
- HUD polls `/health` on `health_endpoint` every 30s
- Reports: `ok` / `degraded` / `down`
- Launchd `KeepAlive` restarts process on crash (exit code ≠ 0)

---

## Example: Creating a Script Agent

### 1. Register Agent
```bash
office-core agents create data-sync \
  --type script \
  --model none \
  --launchd-label com.aryan.office-core.data-sync \
  --health-endpoint http://127.0.0.1:8082/health \
  --schedule "@hourly"
```

### 2. Create Agent Directory
```bash
mkdir -p ~/AI-Office/packages/office-core/agents/data-sync
```

### 3. Write `run.sh`
```bash
#!/bin/bash
# ~/AI-Office/packages/office-core/agents/data-sync/run.sh

set -euo pipefail

LOG_FILE="/Users/aryanagarwal/Library/Logs/com.aryan.office-core.data-sync.log"
exec >>"$LOG_FILE" 2>&1

echo "[$(date)] Starting data-sync"

# Your sync logic here
python3 <<'PYEOF'
import sqlite3
from pathlib import Path

DB = Path.home() / "AI-Office" / "packages" / "office-core" / "tasks.db"
conn = sqlite3.connect(DB)
cursor = conn.cursor()

# Example: Archive completed tasks older than 7 days
cursor.execute("""
    UPDATE tasks SET status = 'archived'
    WHERE status = 'completed'
    AND completed_at < datetime('now', '-7 days')
""")
archived = cursor.rowcount
conn.commit()
print(f"Archived {archived} tasks")
PYEOF

echo "[$(date)] Completed data-sync"
```

### 4. Write `monitor.py` (for health endpoint)
```python
#!/usr/bin/env python3
# ~/AI-Office/packages/office-core/agents/data-sync/monitor.py

from fastapi import FastAPI
import uvicorn
import sqlite3
from pathlib import Path

app = FastAPI()
DB = Path.home() / "AI-Office" / "packages" / "office-core" / "tasks.db"

@app.get("/health")
def health():
    try:
        conn = sqlite3.connect(DB)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "data-sync",
        "database": "connected" if db_ok else "disconnected"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
```

### 5. Make Executable & Deploy
```bash
chmod +x ~/AI-Office/packages/office-core/agents/data-sync/run.sh

# Sync agent → launchd_jobs → generate plists → deploy
office-core launchd sync-agents
office-core launchd generate --deploy
```

### 6. Verify
```bash
# Check launchd loaded
launchctl list | grep data-sync

# Check logs
tail -f ~/Library/Logs/com.aryan.office-core.data-sync.log

# Check health
curl http://127.0.0.1:8082/health
```

---

## Best Practices

1. **Idempotency**: Agents should handle re-runs gracefully (launchd `KeepAlive` restarts on crash)
2. **Logging**: Always log to `~/Library/Logs/{label}.log` (stdout/stderr captured by launchd)
3. **No /tmp logs**: Use `~/Library/Logs/` — survives reboots, visible to HUD
4. **Health endpoint**: Implement `/health` returning JSON with `status` field
5. **Model alias**: Use aliases (`qwen`, `nemotron`) not full model IDs
6. **Graceful shutdown**: Handle SIGTERM (launchd sends before restart)
7. **Environment**: Declare required env vars in `launchd_jobs.environment` JSON