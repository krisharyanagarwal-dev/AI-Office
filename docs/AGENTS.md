# graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# bash agent
- **bash** (`~/.claude/agents/bash.md`) — shell + API specialist (Bash, Read/Write/Edit, Glob/Grep, WebFetch, WebSearch, ToolSearch). Route any "write/debug a shell script", "run this command", "hit this HTTP/REST or MCP API", or "what does this endpoint return" task to it via the Agent tool (`subagent_type: "bash"`). Keys are inherited from the shell env, never hardcoded; keyless endpoints preferred.

# Universal JEV policy
- For every request or task, first identify whether a meaningful typed decision exists. When it does, use JEV as the first-pass decision layer for routing, classification, triage, urgency, confidence, risk, scoring, filtering, and secret/breaking-change gates.
- Use `jev run` or `jev -l` for batches. State observable criteria and thresholds, act only on high-confidence outcomes, and escalate ambiguous or low-confidence decisions.
- Redact secrets and private data before sending state to JEV. Never let JEV execute actions or make irreversible decisions.
- JEV does not generate text or code, perform math/date arithmetic, debug, edit files, run tests, deploy, or replace deterministic tools. Mark JEV inapplicable for those operations and continue with the appropriate tools and reasoning.

# Agent routing index
The local fleet is 24 agents. Never guess which to call — match the user's symptom to a row. Cheap/haiku agents are the default; the sonnet ones are for multi-step or write-capable work.

## Start here (the usual first call)
| Ask | Agent | Why |
|---|---|---|
| "is everything ok?" / "check the bot" | **job-verifier** | multi-lens soundness check on unattended jobs |
| "what's the system state?" (one line) | **launchd-peek** | cheapest single health line for the `com.aryan.*` fleet |
| "did it actually run / produce output?" | **freshness-check** | audits that silence isn't masquerading as success |
| a command, script, or HTTP/API call | **bash** | shell + API specialist |

## Provider / key health (the free chain)
| Ask | Agent |
|---|---|
| "is every free key live?" | **key-keeper** |
| a key died — keep the chain serving | **key-rotation-sentinel** |
| the `.env` key chain is broken | **env-key-doctor** (fixes, unlike the two above) |
| MCP servers won't connect | **mcp-health-warden** |
| "cheapest model for this sub-task" | **free-router** |

## Inspect (all read-only, haiku)
| Ask | Agent |
|---|---|
| git status / diff / log | **git-peek** |
| find a symbol / leg / file | **find-code** |
| read a log | **log-peek** |
| recall a past fact by meaning | **mem-search** |
| a quick number | **calc** |
| metered Codex spend so far | **spend-watch** |

## Repair / write (sonnet, can change things)
| Ask | Agent |
|---|---|
| a service is down or unsupervised | **service-guardian** |
| a new/edited unattended job is unsound | **job-verifier** |
| find the cause of a bug | **bug-scout** (discover stage of bug-heal) |
| disk is filling up | **disk-warden** (read-only audit) |
| unused ollama models eating GBs | **ollama-reaper** |
| verify irreplaceable state still exists | **backup-sentinel** |
| remember this fact for later | **memory-scribe** |

## Quality gates (run these, don't substitute judgement for them)
| Ask | Agent |
|---|---|
| "is this task actually good?" | **task-judge** → then **task-verdict** (capstone go/no-go) |

`task-judge` fans out across every free provider and defaults each of CORRECTNESS / COMPLETENESS / SAFETY to FAIL. `task-verdict` collapses the ledger into one honest go/no-go. Use judge first, verdict second — never verdict alone.

## opencode-only subagent
- **apibot-worker** (`~/.config/opencode/agent/apibot-worker.md`) — free-cloud LLM worker. Offload a one-shot summarize/extract/classify/rank/qa sub-task to Groq-class models at $0 metered instead of doing it inline. Not available to Codex, so it is listed separately.

## Two-machines rule (this laptop vs the mini)
This laptop is the dev surface. `a@macmini` is the live deployment. SSH **by alias** `a@macmini` (bare `a@192.168.29.202` is denied). Both converge through GitHub `origin/main`. Never deploy a whole shared file over the mini's copy when it has diverged — diff, then apply surgically. See the fleet repo's own `AGENTS.md` for the interpreter matrix and quality-gate command.

# Trading-system ground rules
- Paper and TESTNET only unless the user explicitly authorises otherwise. `live_orders_allowed` must stay false and no order path may ever be added to the research/executor code.
- **Gross edge is not profit.** Forward returns are price-relative and pre-cost. Any claim about a strategy being worth trading must go through `cost_model.cost_sensitivity` and state which venue, which fee, and which funding assumption. On Binance spot, maker and taker are BOTH 0.1% at VIP 0 — limit orders save nothing there.
- A horizon may only be called viable when its own confidence interval excludes zero AND it clears modelled costs. "Costs cleared" alone is not an edge.
- Never lower a sample floor or read `ci_includes_zero` as a direction in order to get a verdict.

# Agent + skill trees (verified 2026-11-02)
- `~/.Codex` and `~/.codex` are the **same directory** (inode 98801691, case-insensitive volume). They are not two trees; don't reason about "which case wins".
- Codex agent definitions are `~/.Codex/agents/*.toml` — 22 files, extension `.toml`, **never `.md`**.
- The routing table above describes the **`~/.claude/agents/*.md`** tree (24 entries). Proof: `env-key-doctor` is in the table and exists only in `~/.claude/agents`. Of those 24 entries, `_bak_archive` is an archive dir, not an agent.
- `~/.Codex/skills/` is **empty** — never point a skill at it. Skills live in `~/.claude/skills` (77) and `~/.agents/skills` (74).
- `graphify` therefore exists twice, and the two copies **already differ** (`Claude subagents`/`CLAUDE.md` vs `Codex subagents`/`AGENTS.md`). Nothing detects the day they stop agreeing. If you change one, change both.
