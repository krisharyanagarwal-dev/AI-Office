# AI-Office — Multi-Session Workspace

This directory (`/Users/aryanagarwal/AI-Office`) is the shared workspace for the Office OS agent fleet. Multiple opencode sessions can work here concurrently.

## Structure

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Agent routing index (24 agents, task → agent mapping) |
| `PROJECT_MEMORY.md` | Recovered project state, history, decisions, blockers |
| `SESSION_AVAILABILITY_REGISTER.md` | Registered sessions and their outcomes |
| `office.sh` | Start/stop the office orchestrator + tmux UI + web server |
| `office-os/` | Nested git repo: orchestrator, web server, config, tasks |
| `all-files/json/` | JSON task/data files (13K+ files) |
| `CLAUDE.md` | This file — session entry point |

## Getting Started (for any session)

1. **Check system state** — Read `PROJECT_MEMORY.md` for current blockers and next actions
2. **Check agent routing** — Read `AGENTS.md` to route tasks to the right agent
3. **Start the office** (optional) — `cd office-os && bash office.sh --no-ui`
4. **Check git status** — `git status` to see what other sessions changed
5. **Pull before pushing** — `git pull --rebase` before committing

## Session Coordination

- **Never force-push to main** — use `git pull --rebase` first
- **Commit often** — small, descriptive commits help other sessions see progress
- **Update PROJECT_MEMORY.md** when you make decisions or find blockers
- **Update SESSION_AVAILABILITY_REGISTER.md** when you start/finish a session

## Git Workflow

```
git pull --rebase          # Get others' changes first
git add <files>            # Stage your changes
git commit -m "message"    # Commit locally
git push                   # Share with other sessions
```

## Universal JEV Policy (from AGENTS.md)

For every task, first identify whether a meaningful typed decision exists. Use JEV as the first-pass decision layer for routing, classification, triage, urgency, confidence, risk, scoring, filtering, and secret/breaking-change gates. JEV does not generate text or code, perform math/date arithmetic, debug, edit files, run tests, deploy, or replace deterministic tools.

## Trading-System Ground Rules

- Paper and TESTNET only unless explicitly authorised. `live_orders_allowed` stays false.
- Gross edge is not profit — any strategy claim must go through cost sensitivity analysis.
- Never lower a sample floor or read `ci_includes_zero` as a direction to get a verdict.

## Two-Machines Rule

- This laptop (AI-Office) is the dev surface. `a@macmini` is the live deployment.
- SSH by alias `a@macmini` only. Never deploy a whole shared file over the mini's copy — diff, then apply surgically.
- Both converge through GitHub `origin/main`.

## Key Blockers (from PROJECT_MEMORY.md)

1. Mac mini unreachable — needs physical access (power on + enable Remote Login)
2. Polymarket live data — API not accessible; engine BLOCKED
3. Free Harness rate limit — ~4 requests before 500 errors
4. NVIDIA API timeouts — 5-min timeout on integrate.api.nvidia.com

## Next Actions (Priority Order)

1. Physically access Mac mini → power on, enable Remote Login, verify IP
2. Resolve Polymarket API access → unblocks paper trading engine
3. Deploy agent fleet to Mac mini → once Mac mini online
4. Extend paper trading dry-run validation → run dry_run_test.py
5. Monitor NVIDIA API reliability → recent 5-min timeouts
