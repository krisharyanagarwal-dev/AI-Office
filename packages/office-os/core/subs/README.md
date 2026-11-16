# Qwen3.5-9B Worker Subs

Deployed Qwen3.5-9B worker subsystem for AI-Office multi-session coordination.

## Overview

This directory contains the session-based worker subsystem for spawning and managing Qwen3.5-9B worker instances. Each opencode session can claim dedicated workers to process tasks independently.

## Architecture

- **1 worker** (worker-1) on `127.0.0.1:11434` running `hauhaucs/qwen3.5-9b-uncensored-aggressive`
- **16GB RAM limit** — only 1 concurrent 5.6GB model can run
- **No fallback** — if the worker is down, tasks fail

## Files

| File | Purpose |
|------|---------|
| `worker_pool.json` | Worker pool configuration |
| `session_registry.json` | Session → worker assignments |
| `session_worker_launcher.py` | Spawn/assign/release/list workers |
| `session_task_submit.py` | Submit prompts to session workers |
| `spawn_qwen_subs.sh` | CLI wrapper for all operations |

## Usage

### Spawn workers for a session
```bash
cd /Users/aryanagarwal/AI-Office/office-os/core/subs
./spawn_qwen_subs.sh spawn session-alpha 1
```

### Submit a task to a session
```bash
./spawn_qwen_subs.sh submit session-alpha "Explain what Qwen3.5-9B is in 2 sentences."
```

### Check status
```bash
./spawn_qwen_subs.sh status
./spawn_qwen_subs.sh list
```

### Release workers
```bash
./spawn_qwen_subs.sh release session-alpha worker-1
```

### Python API
```bash
python3 session_worker_launcher.py spawn <session_id> [count]
python3 session_worker_launcher.py status
python3 session_task_submit.py <session_id> "<prompt>"
```

## Multi-Session Workflow

Each opencode session should:
1. Spawn its own workers: `./spawn_qwen_subs.sh spawn session-<name> 1`
2. Submit tasks: `./spawn_qwen_subs.sh submit session-<name> "<prompt>"`
3. Release when done: `./spawn_qwen_subs.sh release session-<name> worker-1`

Since only 1 worker fits in 16GB RAM, sessions must coordinate worker access. Only 1 session can have an active worker at a time.

## Integration with JEV Dispatcher

The JEV dispatcher (`office-os/core/subs/../jev-dispatcher.py` or `.openclaw/jev-dispatcher.py`) prompts models directly via `/v1/completions`. It reads `worker_pool.json` for the worker endpoint and saves results to `.openclaw/autonomous-qwen/results/`.

## Model

- `hauhaucs/qwen3.5-9b-uncensored-aggressive` (Q4_K_M GGUF, 5.6 GB)
- Running via Ollama llama-server on port 11434
- OpenAI-compatible `/v1/completions` endpoint