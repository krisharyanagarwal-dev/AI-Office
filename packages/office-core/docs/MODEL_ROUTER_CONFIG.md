# Model Router Configuration

## Overview

The Model Router is the single gateway for all LLM inference in office-core. It abstracts backend diversity (MLX, NIM, free-harness) behind a unified interface with priority-based routing, automatic fallbacks, and health-aware load balancing.

**Config Sources** (in priority order):
1. `model-router.yaml` — Static config (version controlled)
2. `model_routes` table — Runtime overrides (via CLI/API)
3. Environment variables — Secrets (API keys)

---

## Backend Definitions

### mlx-local (Primary)
```yaml
- name: mlx-local
  type: mlx
  endpoint: "http://127.0.0.1:11435"  # Mini's MLX via SSH tunnel
  models:
    - "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4"
    - "qwen3:8b"
    - "qwen2.5:7b"
    - "qwen2.5:0.5b"
    - "llama3.2:3b"
    - "gemma3:1b"
  priority: 100
  enabled: true
  config:
    timeout: 180
    max_tokens: 8192
```

**Architecture**: Laptop → SSH tunnel (11435) → Mini:11435 (ollama_shim) → MLX server

### nim-cloud (High-Capability)
```yaml
- name: nim-cloud
  type: nim
  endpoint: "http://127.0.0.1:4200"  # Mini's NIM proxy
  models:
    - "nvidia/nemotron-3.5-lightning-30b-a3b"
    - "nvidia/nemotron-3-ultra-550b-a55b"
    - "nvidia/nemotron-3.5-super-vl-120b-a12b"
    - "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
  priority: 50
  enabled: true
  config:
    timeout: 90
    max_tokens: 4096
    api_key_env: "NVIDIA_API_KEY"
```

**Architecture**: Laptop → SSH tunnel (4200) → Mini:4200 (NIM proxy) → NVIDIA NIM

### free-harness (Fallback)
```yaml
- name: free-harness
  type: free-harness
  endpoint: "http://127.0.0.1:19593"  # qwen9 bridge on laptop
  models:
    - "qwen9"
    - "qwen3:8b"
  priority: 10
  enabled: true
  config:
    timeout: 60
    max_tokens: 4096
```

**Architecture**: Local laptop process (port 19593) → free provider APIs (Groq, Cerebras, etc.)

### ollama-local (Disabled)
```yaml
- name: ollama-local
  type: ollama
  endpoint: "http://127.0.0.1:11434"
  models: []  # Dynamic from /api/tags
  priority: 5
  enabled: false  # Replaced by MLX shim
  config:
    timeout: 120
```

---

## Routing Rules

Evaluated **in order** — first match wins.

```yaml
routing_rules:
  - name: "mlx-preferred"
    condition: "model in mlx-local.models"
    backend: "mlx-local"
    fallback: "nim-cloud"

  - name: "nim-large"
    condition: "model in nim-cloud.models"
    backend: "nim-cloud"
    fallback: "mlx-local"

  - name: "free-harness-fallback"
    condition: "true"
    backend: "free-harness"
    fallback: null
```

### Rule Fields
| Field | Description |
|-------|-------------|
| `name` | Identifier for debugging |
| `condition` | Python-like expression (model, backend, priority available) |
| `backend` | Target backend name |
| `fallback` | Backend to try if primary fails (null = no fallback) |

### Condition Variables
- `model` — Requested model name/alias
- `backend` — Backend name being evaluated
- `priority` — Backend priority (int)
- `healthy` — Boolean, true if backend passed recent health check

---

## Model Aliases

Short names → full model IDs. Defined in `model-router.yaml`:

```yaml
aliases:
  "qwen": "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4"
  "qwen3": "qwen3:8b"
  "qwen2.5": "qwen2.5:7b"
  "llama3": "llama3.2:3b"
  "nemotron": "nvidia/nemotron-3.5-lightning-30b-a3b"
  "nemotron-ultra": "nvidia/nemotron-3-ultra-550b-a55b"
```

**Usage**: Agents call router with `model: "qwen"` — router resolves alias → finds backend via routing rules.

---

## Health Checks

```yaml
health_check:
  interval: 60        # seconds between checks
  timeout: 10         # request timeout
  unhealthy_after: 3  # consecutive failures before marking down
```

### Health Check Logic
1. Every `interval` seconds, router calls `GET /health` on each backend
2. Success = HTTP 200 + valid response
3. Failure increments counter; success resets to 0
4. Counter ≥ `unhealthy_after` → backend marked `unhealthy`
5. Unhealthy backends **skipped** in routing (fallback used instead)
6. On recovery (success), counter resets → backend re-enabled

### Backend Health Endpoints
| Backend | Health Endpoint |
|---------|-----------------|
| mlx-local | `http://127.0.0.1:11435/health` (via tunnel) |
| nim-cloud | `http://127.0.0.1:4200/health` (via tunnel) |
| free-harness | `http://127.0.0.1:19593/health` (local) |

---

## Rate Limits

Per-backend limits enforced by router:

```yaml
rate_limits:
  mlx-local:
    requests_per_minute: 30
    concurrent: 1
  nim-cloud:
    requests_per_minute: 100
    concurrent: 5
  free-harness:
    requests_per_minute: 60
    concurrent: 2
```

- **requests_per_minute**: Token bucket refill rate
- **concurrent**: Max simultaneous requests (queue excess)
- Exceeding → HTTP 429 with `Retry-After` header

---

## Adding New Backends

### 1. Add to `model-router.yaml`
```yaml
- name: openai-api
  type: openai
  endpoint: "https://api.openai.com/v1"
  models:
    - "gpt-4o"
    - "gpt-4o-mini"
  priority: 75
  enabled: true
  config:
    timeout: 60
    max_tokens: 4096
    api_key_env: "OPENAI_API_KEY"
```

### 2. Add Routing Rule
```yaml
routing_rules:
  - name: "openai-premium"
    condition: "model in openai-api.models"
    backend: "openai-api"
    fallback: "mlx-local"
  # ... existing rules
```

### 3. Add Aliases (Optional)
```yaml
aliases:
  "gpt4": "gpt-4o"
  "gpt4-mini": "gpt-4o-mini"
```

### 4. Deploy
```bash
# Via CLI (updates DB)
office-core models add openai-api openai https://api.openai.com/v1 \
  --models "gpt-4o,gpt-4o-mini" \
  --priority 75 \
  --config '{"api_key_env": "OPENAI_API_KEY", "timeout": 60}'

# Or edit YAML and restart router
```

---

## Adding New Models to Existing Backend

### Via CLI
```bash
office-core models add mlx-local mlx http://127.0.0.1:11435 \
  --models "new-model-name" \
  --priority 100
```

### Via YAML
Edit `model-router.yaml`, add to `models` array under the backend, restart router.

---

## Mini Deployment

### Required SSH Tunnels (Laptop → Mini)
```bash
# ~/.ssh/config
Host macmini
  HostName 192.168.29.202
  User a
  ControlMaster auto
  ControlPath ~/.ssh/control-%r@%h:%p
  ControlPersist 10m

# Tunnels (run via launchd or tmux)
ssh -L 11434:127.0.0.1:11434 -L 11435:127.0.0.1:11435 -N macmini
ssh -L 4200:127.0.0.1:4200 -N macmini
```

### Environment Variables (Mini)
```bash
# Mini's ~/.zshrc or launchd environment
export NVIDIA_API_KEY="nvapi-..."
export MLX_MODEL_PATH="/Users/a/models"
export OLLAMA_HOST="0.0.0.0:11434"
```

### Launchd for Tunnels (on Laptop)
```xml
<!-- ~/Library/LaunchAgents/com.aryan.office-core.tunnels.plist -->
<dict>
    <key>Label</key><string>com.aryan.office-core.tunnels</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/ssh</string>
        <string>-L</string><string>11434:127.0.0.1:11434</string>
        <string>-L</string><string>11435:127.0.0.1:11435</string>
        <string>-L</string><string>4200:127.0.0.1:4200</string>
        <string>-N</string><string>macmini</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.tunnels.log</string>
    <key>StandardErrorPath</key><string>/Users/aryanagarwal/Library/Logs/com.aryan.office-core.tunnels.err.log</string>
</dict>
```

---

## Router API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models` | List configured routes |
| POST | `/models` | Add/update route |
| POST | `/models/complete` | **Main inference endpoint** |
| GET | `/models/health` | Health status of all backends |

### Completion Request
```json
POST /models/complete
{
  "model": "qwen",
  "prompt": "Explain quantum computing",
  "max_tokens": 2048,
  "temperature": 0.7,
  "stream": false
}
```

### Completion Response
```json
{
  "completion": "Quantum computing uses...",
  "model": "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4",
  "backend": "mlx-local",
  "usage": {"prompt_tokens": 15, "completion_tokens": 256}
}
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| "No healthy backend" | `curl http://127.0.0.1:8080/models/health` — verify tunnels, Mini services |
| High latency | Check `mlx-local` concurrent=1 queue; consider `nim-cloud` for parallel |
| 429 errors | Rate limit hit — check `rate_limits` config, add backends |
| Wrong model used | Verify alias resolution + routing rule order |
| SSH tunnel drops | `autossh` or launchd `KeepAlive`; check `ControlPersist` in SSH config |