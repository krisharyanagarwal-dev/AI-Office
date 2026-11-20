# Launchd Management

## Overview

office-core uses **launchd** (macOS native service manager) for all daemon orchestration. No Docker, no systemd, no external process supervisors. The `launchd_jobs` table in SQLite is the **single source of truth** — plists are generated from it and deployed to `~/Library/LaunchAgents/`.

---

## Generator: `scripts/generate_launchd.py`

### Usage
```bash
# Generate plists to version-controlled directory only
office-core launchd generate

# Generate AND deploy to ~/Library/LaunchAgents (load with launchctl)
office-core launchd generate --deploy

# Sync launchd_jobs from agent registry (agents with launchd_label)
office-core launchd sync-agents

# List registered jobs
office-core launchd list
```

### Output Locations
| Path | Purpose |
|------|---------|
| `~/AI-Office/office-core/launchd/` | **Version-controlled** plists (git-tracked) |
| `~/Library/LaunchAgents/` | **Active** plists (loaded by launchd) |

---

## Source of Truth: `launchd_jobs` Table

```sql
CREATE TABLE launchd_jobs (
    label TEXT PRIMARY KEY,                    -- com.aryan.office-core.service-name
    agent_name TEXT NOT NULL,                  -- FK to agents.name
    program TEXT NOT NULL,                     -- JSON array: ["/usr/bin/python3", "/path/script.py"]
    working_directory TEXT,                    -- Working dir for process
    environment TEXT,                          -- JSON object: {"KEY": "value"}
    run_at_load BOOLEAN DEFAULT 1,             -- Start immediately on load
    keep_alive BOOLEAN DEFAULT 1,              -- Restart on exit (crash or clean)
    throttle_interval INTEGER DEFAULT 30,      -- Min seconds between restarts
    start_calendar_interval TEXT,              -- JSON for scheduled runs (cron-like)
    standard_out_path TEXT,                    -- Stdout log path
    standard_error_path TEXT,                  -- Stderr log path
    process_type TEXT DEFAULT 'Background',    -- Background, Standard, Adaptive
    enabled BOOLEAN DEFAULT 1,
    FOREIGN KEY (agent_name) REFERENCES agents(name)
);
```

### Creating Jobs Manually (CLI)
```bash
office-core launchd create \
  --label com.aryan.office-core.my-service \
  --agent-name my-agent \
  --program '["/usr/bin/python3", "/path/to/daemon.py"]' \
  --working-directory /path/to/working/dir \
  --environment '{"API_KEY": "secret"}' \
  --run-at-load true \
  --keep-alive true \
  --throttle-interval 30 \
  --standard-out-path ~/Library/Logs/com.aryan.office-core.my-service.log \
  --standard-error-path ~/Library/Logs/com.aryan.office-core.my-service.err.log
```

### Creating Jobs from Agents (Auto-Sync)
```bash
# 1. Register agent with launchd_label
office-core agents create my-agent \
  --type daemon \
  --launchd-label com.aryan.office-core.my-agent \
  --schedule "*/5 * * * *"

# 2. Sync creates launchd_jobs entry
office-core launchd sync-agents

# 3. Generate & deploy
office-core launchd generate --deploy
```

**Auto-sync logic** (`scripts/generate_launchd.py::sync_from_agents`):
- Reads all enabled agents with `launchd_label`
- Skips if job already exists
- Infers `program` from `agent.type`:
  - `llm` → `agents/{name}/run.py`
  - `script` → `agents/{name}/run.sh`
  - `daemon` → `agents/{name}/daemon.py`
  - `bridge` → `agents/{name}/bridge.py`
  - `monitor` → `agents/{name}/monitor.py`
- Parses `schedule`:
  - `@hourly`, `@daily`, `@weekly`, `@monthly` → `StartCalendarInterval`
  - Cron expression (`"*/5 * * * *"`) → `StartCalendarInterval` with Minute/Hour/Day/Weekday
- Sets log paths to `~/Library/Logs/{label}.log` / `.err.log`

---

## Deploying Plists

### Generated Plist Structure
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.aryan.office-core.my-service</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/aryanagarwal/AI-Office/office-core/agents/my-agent/daemon.py</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/aryanagarwal/AI-Office/office-core/agents/my-agent</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>API_KEY</key><string>secret</key>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.my-service.log</string>
    <key>StandardErrorPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.my-service.err.log</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Minute</key><string>*/5</string>
    </dict>
</dict>
</plist>
```

### Deploy Process (`generate_all(deploy=True)`)
1. Read all enabled `launchd_jobs`
2. Generate plist dict → write to `~/AI-Office/office-core/launchd/{label}.plist`
3. If `--deploy`:
   - Copy to `~/Library/LaunchAgents/{label}.plist`
   - `launchctl unload -w` (if already loaded)
   - `launchctl load -w` (load new version)
4. Print status for each job

---

## Log Locations

**Standard location**: `~/Library/Logs/{label}.log` / `{label}.err.log`

| Job Label | Stdout Log | Stderr Log |
|-----------|------------|------------|
| `com.aryan.office-core.api` | `~/Library/Logs/com.aryan.office-core.api.log` | `...api.err.log` |
| `com.aryan.office-core.data-sync` | `~/Library/Logs/com.aryan.office-core.data-sync.log` | `...data-sync.err.log` |
| `com.aryan.office-core.tunnels` | `~/Library/Logs/com.aryan.office-core.tunnels.log` | `...tunnels.err.log` |

### Viewing Logs
```bash
# Tail live
tail -f ~/Library/Logs/com.aryan.office-core.api.log

# Search errors
grep -i error ~/Library/Logs/com.aryan.office-core.*.err.log

# Follow multiple
tail -f ~/Library/Logs/com.aryan.office-core.*.log
```

---

## Best Practices

### 1. No `/tmp` Logs
```python
# BAD - lost on reboot, not visible to HUD
standard_out_path: "/tmp/my-service.log"

# GOOD - persistent, indexed by label
standard_out_path: "/Users/aryanagarwal/Library/Logs/com.aryan.office-core.my-service.log"
```

### 2. Label = Filename
```python
# Label MUST match plist filename (without .plist)
Label: "com.aryan.office-core.my-service"
# File: ~/Library/LaunchAgents/com.aryan.office-core.my-service.plist
```

### 3. KeepAlive = true (Almost Always)
```python
# Daemons, workers, API servers — always restart
keep_alive: true

# Only disable for one-shot cron jobs
keep_alive: false
start_calendar_interval: {"Hour": 2, "Minute": 0}  # Daily at 2 AM
```

### 4. ThrottleInterval
```python
# Prevent restart loops (default 30s)
throttle_interval: 30

# For flaky services, increase
throttle_interval: 60
```

### 5. ProcessType
| Type | Use Case |
|------|----------|
| `Background` | Default — daemons, workers, APIs |
| `Standard` | Interactive apps (rare) |
| `Adaptive` | Low-priority background work |

### 6. Environment Variables
```python
# Define in launchd_jobs.environment (JSON)
environment: {
    "PYTHONPATH": "/Users/aryanagarwal/AI-Office/packages/office-core",
    "MODEL_ROUTER_URL": "http://127.0.0.1:8080",
    "API_KEY": "secret-from-keychain"
}
```
**Secrets**: Store in macOS Keychain, reference via `security find-generic-password` in wrapper script, or use launchd `EnvironmentVariables` with values injected at deploy time.

### 7. WorkingDirectory
```python
# Always set explicitly — avoids "file not found" on relative paths
working_directory: "/Users/aryanagarwal/AI-Office/office-core/agents/my-agent"
```

---

## Common Commands

```bash
# List office-core jobs loaded in launchd
launchctl list | grep com.aryan

# Check job status
launchctl print gui/$(id -u)/com.aryan.office-core.api

# Manual load/unload
launchctl load -w ~/Library/LaunchAgents/com.aryan.office-core.api.plist
launchctl unload -w ~/Library/LaunchAgents/com.aryan.office-core.api.plist

# View generated plist (before deploy)
cat ~/AI-Office/office-core/launchd/com.aryan.office-core.api.plist

# Edit job in DB, then redeploy
office-core launchd generate --deploy

# Disable job without deleting
# UPDATE launchd_jobs SET enabled=0 WHERE label='...';
office-core launchd generate --deploy
```

---

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Job not starting | `launchctl print` shows "not loaded" | `office-core launchd generate --deploy` |
| Job crash-looping | Logs show repeated exits, `ThrottleInterval` firing | Fix code bug; increase `throttle_interval` |
| Logs not appearing | Wrong `StandardOutPath` | Use `~/Library/Logs/{label}.log` |
| Env vars missing | `printenv` in script shows empty | Set in `launchd_jobs.environment` JSON |
| Schedule not firing | `StartCalendarInterval` malformed | Validate JSON; use `@daily` shortcut in agent schedule |
| "Could not find service" | Label mismatch | Label = plist filename (no `.plist`) |

---

## Mini Deployment Note

For services running on **Mac Mini**, use the same pattern but deploy the plist on the Mini:
```bash
# On laptop: generate plist
office-core launchd generate

# Copy to Mini
scp ~/AI-Office/office-core/launchd/com.aryan.office-core.mini-service.plist macmini:~/Library/LaunchAgents/

# On Mini: load
ssh macmini launchctl load -w ~/Library/LaunchAgents/com.aryan.office-core.mini-service.plist
```

Or use `deploy-service-to-mini` playbook for automated deploy.