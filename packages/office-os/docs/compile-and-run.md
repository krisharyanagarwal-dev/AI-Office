# Compile and Run — big models author, free workers execute

**Status:** design, not built. **Date:** 2026-11-22.
**Scope:** how the office uses an expensive model (Claude) as a *compiler* and the free
pools (Nemotron via the NVIDIA keys, Groq, Cerebras, local MLX) as the *runtime*.

---

## 1. The inversion

The thing to get right is **which model does which job**:

| | Compile-time | Run-time |
|---|---|---|
| Who | Claude / a big model | free workers (Nemotron 30B/550B, Groq, Cerebras, MLX) |
| How often | rarely — once per job, then on failure | constantly — every 30 min, 24 rounds/day |
| Produces | a versioned **job spec** committed to git | one schema-valid record per run |
| Costs | metered, budgeted, logged | $0 |
| Judged by | the human, on review | deterministic checks, then the free chain |

Claude's output is **not an answer**. It is an asset: a prompt plus a contract that a
cheap model can execute thousands of times without supervision. One good compile pass
amortises over hundreds of free runs. That is the whole economic case.

### What is backwards today

`core/agent_factory.py` is the existing "factory", and it has the polarity reversed:
it calls the **free** cloud pools to mass-generate agent specs — "1 LLM call -> 10 agent
specs (max throughput batch generation)". That is how 327 persona files came to hold the
*identical* `model:` line and interchangeable, tautological rules ("You measure drawdown:
the peak-to-trough decline"). Cheap models wrote the prompts, and cheap models then ran
them, so nothing in the chain was ever high-quality.

It is also dead code: its `CONFIG_PATH` points at `/Users/aryanagarwal/AI-Office/office-os/config/office.json`,
which does not exist (the tree moved to `packages/office-os`). Do not extend it. Replace
its role: batch quantity out, compiled quality in.

---

## 2. The unit of work: a job spec

One file per job, in `packages/office-os/jobs/<job-id>.json`, in git. Claude writes these.

```json
{
  "id": "cost-sensitivity-gate",
  "agent": "cost-analyst",
  "tier": "lite",
  "source": "paper-book",
  "prompt": "Given the exits in <evidence>, report the fee level at which this edge dies...",
  "output_schema": {
    "verdict": ["CLEARS", "FAILS", "NOT_COSTABLE", "NO_EVIDENCE"],
    "venue": "string",
    "fee_tier": "string",
    "gross_bps": "number|null",
    "net_bps": "number|null",
    "dies_at_fee_pct": "number|null",
    "exits": "integer",
    "cites": "string"
  },
  "acceptance": [
    "verdict in schema",
    "cites names a real survey line",
    "verdict==CLEARS implies net_bps != null and dies_at_fee_pct != null",
    "verdict==CLEARS implies exits >= 30",
    "NO_EVIDENCE is valid and requires cites to name the dead source"
  ],
  "escalate_when": ["3 consecutive schema failures", "judge rejects 2 of 3 runs"],
  "budget": {"free_calls_per_day": 24, "claude_calls_per_week": 2}
}
```

Three things make this work where a persona alone does not:

1. **The output is a record, not prose.** Today a round produces 120 words of English that
   nothing can check. A JSON record with an enum verdict can be validated for free, in
   microseconds, with no model involved.
2. **`NO_EVIDENCE` is a success.** A worker that abstains correctly has done its job. This
   is the only honest way to run agents whose source is dead, and it is what stops a free
   model filling a gap from memory.
3. **`acceptance` is executable.** "CLEARS implies exits >= 30" is a line of Python, not a
   guardrail an agent may or may not have read. Guardrails in prose are advisory; a floor
   in `acceptance` is a gate.

---

## 3. The verification ladder

Climb only as far as needed. Each rung costs more than the last.

| Rung | Cost | Catches |
|---|---|---|
| 1. JSON parse + schema | $0, deterministic | malformed output, invented enum values |
| 2. `acceptance` assertions | $0, deterministic | a CLEARS verdict with no cost model, a sample floor quietly lowered |
| 3. JEV typed gate | $0 | routing, urgency, confidence, risk banding — every decision that is a *classification*, not generation |
| 4. free-chain consensus (`task-judge`) | $0 metered | reasoning that is well-formed but wrong |
| 5. Claude | metered, budgeted | only a job spec that keeps failing rungs 1–4 |

Per the standing JEV policy, rung 3 handles the typed decisions and never generates text or
executes anything; ambiguous or low-confidence outcomes escalate rather than resolve.

Rungs 1–2 are the ones missing today and the ones that buy the most. A 30B model held to a
tight schema with a retry is *reliable*; the same model asked for "at most 120 words,
concretely" is a coin flip — this week it answered as a blockchain security auditor.

---

## 4. How it develops independently

The loop that closes without a human:

```
free workers run the job 24x/day
        │
        ├─ schema + acceptance pass  → record appended, nothing to do
        │
        └─ fail / abstain / judge-reject
                  │
                  └─ failures aggregate in jobs/<id>.failures.jsonl
                            │
                            └─ threshold hit (escalate_when)
                                      │
                                      └─ ONE Claude compile pass reads the
                                         failures and rewrites the job spec
                                         → commit → workers pick it up
```

**The workers' failures are the compiler's input.** That is what makes this independent
rather than merely automated: Claude is never in the per-task path, only in the
per-*pattern* path, and it sees aggregated evidence of what the cheap model could not do.

Two hard limits on the loop, so independence cannot run away:

- **Budget.** `claude_calls_per_week` per job, counted and logged. Exhausted budget freezes
  the job rather than silently spending.
- **Freeze on repeat.** A job that escalates twice without its failure rate dropping stops
  and waits for the human. A compiler that keeps failing to fix something must not keep
  trying at a cost.

---

## 5. Where each half runs — the laptop compiles, the mini executes

The split falls on the existing two-machines rule: **the laptop is the dev surface, the
Mac mini is the live deployment.** Compile-time is a laptop activity; run-time belongs on
the mini. Verified on 2026-11-22:

| | Laptop (compile) | Mac mini (execute) |
|---|---|---|
| Reachable | — | `a@macmini` (alias only; bare IP is denied) |
| Host | macOS, Python **3.14** | macOS 27.0, arm64, **16 GB RAM**, Python **3.9.6 only** |
| Checkout | `~/AI-Office` @ `dost-subpackages` | `~/ai-office-src` @ `dost-subpackages`, clean, same GitHub remote |
| Models | Claude; NVIDIA keys (Nemotron 550b/30b), Groq, Cerebras | **local ollama on `:11434`** — Qwen 2.5 (0.5b/7b), Qwen3 8b, Qwen3.5 9b, Llama 3.2 3b, Gemma3 1b |
| Keys in `~/.env` | NVIDIA ×4, Gemini, Groq, OpenRouter | **`GEMINI_API_KEY` only** |
| launchd | the office orchestrator | **114 `com.aryan.*` jobs** already running |

### What this forces

1. **The workers are local models, not Nemotron.** The mini holds no NVIDIA key, and
   copying keys between machines is forbidden. So the mini's worker pool is *ollama first,
   Gemini second*. Nemotron-550b stays a **compile-side** resource on the laptop — useful
   for drafting a job spec cheaply before Claude refines it, not for running the job.
   Correct the mental model: "Nemotron on my hood" is really *Qwen/Llama on the mini*.
2. **The runner must be Python 3.9, stdlib only.** No 3.10+ syntax, no `match`, no
   `tomllib`, no pydantic or jsonschema. This is not theoretical: an f-string with nested
   quotes written on the laptop failed on the mini mid-inventory. `core/ops_probes.py`
   already honours this (`MINI_SCRIPT` runs under "`/usr/bin/python3` (3.9, stdlib + yaml)")
   — follow that precedent, and keep `output_schema` a plain dict rather than real JSON
   Schema precisely so a stdlib validator can read it.
3. **Memory is the real budget, not tokens.** 16 GB with ~4.7 GB of swap already in use.
   One resident worker model with a sane `keep_alive` beats eight; model choice matters more
   than prompt cleverness. A 9b worker is affordable, a 120b is not.
4. **The runner is job 115.** Its own launchd label, `KeepAlive`, logs to `/tmp` (never
   under `~/Documents` — that is the exit-78 TCC trap), and it never touches a trading or
   kill-switch job.

### Transport: git down, ssh up

```
laptop:  Claude compiles  →  jobs/<id>.json  →  commit  →  push origin/main
                                                              │
mini:    git -C ~/ai-office-src pull --ff-only  ←─────────────┘
                   │
                   └─ runner (3.9, stdlib) executes against local ollama
                            │
                            └─ records/failures → one ssh call → laptop survey line
```

- **Code and specs travel by git**, because both machines already converge on the same
  GitHub remote and the mini's checkout is clean. Never `scp` a shared file over the mini's
  copy; if a file has diverged, diff and apply surgically.
- **Records travel by ssh, not git.** They are data, and committing them from the live box
  would pollute history and invite divergence. Use the proven pattern: one ssh call per
  cycle returning JSON, exactly as `ops_probes.mini_probe()` does today, surfaced as an
  ordinary collector so the whole verification ladder applies to it.
- **The mini never compiles.** It holds no Claude key and writes no job spec. If the mini
  could author its own prompts there would be no compile gate at all, and the quality
  argument in §1 collapses.

## 6. The five scars this design must respect

Each of these was a live defect in this office on 2026-11-21/22. A design that ignores them
reproduces them.

1. **Silence is not success.** The autopilot emitted `autopilot_round_started` 10 times and
   `finished` zero times for five days, and the only symptom was a missing file. Every job
   run emits a start *and* a terminal event, and the absence of a terminal event is itself
   a reported defect — not an absence of news.
2. **Evidence or abstain.** Seven departments cite retired collectors and answer anyway.
   A job whose `source` is not in `sources.COLLECTORS` must return `NO_EVIDENCE`, and the
   runtime should refuse to dispatch it at all.
3. **Context hygiene.** A five-day-old round-up was injected into every round as "Previous
   round-up" and steered both questions and answers. Everything entering a prompt carries a
   timestamp and a max age, and unstamped context is dropped.
4. **A monitor that cries wolf is worse than none.** `office-cadence` produced three false
   positives in two days (lifetime totals after a fix, a spent daily budget read as a
   stall). Acceptance checks are judged against the *current* regime, and a rule that fires
   on correct behaviour is a bug in the rule.
5. **A producer never verifies its own work.** The model that wrote a record never judges
   it. Rungs 1–2 are code; rung 4 is a different pool than the one that produced the output.

Unchanged and non-negotiable: paper/testnet only, `live_orders_allowed` stays false, no
order path, `executor_enabled: false` until each rung above is in place, presence-only on
keys, and the two-machines rule (laptop dev, mini live, surgical changes).

---

## 7. What blocks this today

Honest list, worst first:

1. **Seven blind departments.** Independent development is impossible without ground truth —
   the workers would develop against nothing. A collector serving real paper-book state and
   market data is the precondition for everything above, not a later nicety.
2. **Local inference is live on the mini and dead on the laptop.** On the mini, ollama
   answers on `:11434` with Qwen/Llama/Gemma available — so "free workers on my hood" is
   *true*, as long as the hood is the mini. On the laptop the binary exists at
   `~/.local/bin/ollama` but the daemon answers nothing, `ollama` is not a provider in
   `opencode.json`, and the new `mlx_local` pool sits at the head of `fallback_chain` with
   no entry in `provider_client.KEY_NAMES`, so constructing it raises. That matters less
   once execution moves to the mini, but the broken `mlx_local` hop should still be fixed
   or removed: every fallback traversal currently wastes its first attempt.
3. **No contract layer.** Nothing in `core/` knows what a valid output is. `_ask()` returns
   text and `extract_answer()` looks for a final answer; there is no schema, no acceptance,
   no failure log.
4. **No compile artifact.** Big-model output currently lands in a chat and evaporates. There
   is no `jobs/` directory and nothing versioned for a worker to execute.

---

## 8. Build order

Smallest first, each step useful alone:

1. **One real collector** for the paper book, so one department stops being blind.
   (Unblocks everything; nothing below is meaningful without it.) *Laptop.*
2. **A 3.9 stdlib runner on the mini**, driven by one job spec: pull, read the spec, call
   local ollama, validate against `output_schema`, append to `records.jsonl` /
   `failures.jsonl`. Run it by hand over ssh first — no launchd, no KeepAlive. *Mini.*
3. **Surface its records as a collector** over one ssh call, so the laptop can see what the
   mini produced and `ops_check` covers it. *Both.*
4. **One job spec compiled properly by Claude** for a department that has evidence — run it
   free for a day on the mini and read the failure log.
5. **`acceptance` assertions** as executable checks, promoted out of the charter prose.
6. **launchd job 115 + escalation + budget**, then and only then widen to more jobs.

Steps 2–6 are each about a day. Step 1 still needs a decision from you: revive a collector,
or retire the departments that have none. Nothing above step 3 is trustworthy without it —
a worker on the mini with no evidence is just a faster way to generate confident nonsense.
