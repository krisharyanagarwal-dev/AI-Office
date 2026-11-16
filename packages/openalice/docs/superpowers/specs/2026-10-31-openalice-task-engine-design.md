# OpenAlice Command Center — Task-State Authority Design

**Date:** 2026-10-31
**Status:** Approved design. This document authorizes nothing except its own existence. No implementation code exists as of this commit.
**Repo:** `/Users/aryanagarwal/openalice-command-center` @ `main`, no remote configured.
**Author identity:** existing global git identity `goodwearrinfo-aryan <goodwearr.info@gmail.com>`, the same author recorded on recent commits in `openalice-fleet` and `openalice-ui`. No identity was invented for this repo.

---

## 1. Governing documents and reconciliation

Two documents describe this system and they conflict. The reconciliation below is the adopted position.

| Concern | Attached MASTER BUILD PROMPT (15 sections) | OpenAlice 10K Office design (20 sections) | **Adopted here** |
|---|---|---|---|
| May anything be implemented? | Yes, now | Line 3 and §18: "Design proposal only… Implementation and operational changes are not authorized" | **The attached prompt governs.** The 10K doc's non-authorization is superseded for this project only, by explicit owner decision on 2026-10-31. |
| Dashboard capability | §2: chat, approvals, cancel/pause | §1: office is read-only and "cannot schedule, dispatch, execute, approve, cancel, deploy, or reconfigure" | **Control-capable**, but every control route is gated by §13's action classes. Read-only projections remain the default surface. |
| Where work executes | §6: adapters to local sessions, local runners, git | §1: cloud is the only proposed worker environment; neither Mac executes workers | **Local execution on this Mac**, bounded by measured disk and provider concurrency. |
| Scale | §4: 20 session slots | 10,000 logical role profiles; "registration does not start a process" | **10K roles as catalogue rows, one small measured worker pool.** See §8. |
| Provider for reasoning | §3: OpenAI as primary reasoning engine; §6 keeps workers NVIDIA-only | OpenAI appears only as the disabled Codex/Agents-API lane; "no silent fallback to OpenAI if NVIDIA is unavailable" | **Provider-agnostic reasoning adapter, `groq` live today, OpenAI unconfigured.** Not a conflict: the attached prompt does not route *worker* inference through OpenAI. See §12. |

### 1.1 Standing constraints that were not overridden

These come from `~/agents.md` and the attached prompt §10, and remain in force regardless of the reconciliation above:

- Worker inference stays NVIDIA-only; fail-clear; no automatic provider fallback.
- No Anthropic paid fallback. No OpenRouter for OpenAlice worker workloads.
- Trading remains PAPER-only. `live_orders_allowed` stays false. No order path, no live endpoint, no trading credential reaches this project.
- No changes to the existing HUD, its deployment, launchd services, or trading configuration.
- No secrets in Git, prompts, logs, or reports.
- No destructive Git commands, no force-push, no automatic merges.
- No automatic cloud deployment and no public synchronization.

### 1.2 A citation defect recorded so it is not inherited

Four sessions on 2026-10-31 cited "Section 20 permissions" as the basis for their authority. Section 20 of the 10K design is titled *"Design-only acceptance matrix — nonproduction worker isolation"* and states "**No dispatch is authorized by this matrix**". One session extended this to "Bounded reversible code changes: permitted per Section 20". That claim is unfounded. Their read-only behaviour was correct under §17's smallest-safe-next-step; the section they named grants nothing. Future work in this repo cites sections only for what they actually say.

---

## 2. Scope

**In v1:** the task-state authority (transitions, fencing, leases, outbox), the role catalogue, the bounded worktree pool with automatic allocation and merge-back, four adapter discovery interfaces, audit/traceability, the tests in §17, and a dashboard showing loop state and one prompt's full fan-out.

**Out of v1, named so it is not mistaken for done:** cloud workers, multi-host scheduling, cost/budget enforcement with numeric ceilings, policy versioning with urgent revocation, quorum and authority failover, the 14-page navigation of the attached §2, and any trading-adjacent integration.

**Scope judgement:** this is one implementation plan, not several, because every element above is in service of a single invariant — one writer, fenced. Build order is decided in the plan, not here; the ordering constraint worth stating now is that the transition authority (§6–§7) must land and pass §17.1–17.3 before the worktree pool (§9) or any dashboard page, because both are meaningless without the thing that makes a stale write inert.

---

## 3. Evidence baseline

Every quantitative claim in this design was measured on 2026-10-31 between 20:20 and 20:55 IST. These numbers, not the reports they replace, are the design's inputs.

| Fact | Value | How measured |
|---|---|---|
| opencode session rows, laptop | 71,544 | `select count(*) from session` on `~/.local/share/opencode/opencode.db` (9,777,840,128 bytes) |
| …of which a single batch | 70,705 rows, all `directory=/Users/aryanagarwal/openalice-fleet/scripts`, spanning 2026-09-15 12:44 → 2026-09-24 23:01 | grouped by `directory`, bounded by `time_updated` |
| Non-batch sessions ever, laptop | 839 | subtraction of the two rows above |
| Laptop sessions updated in last 24 h / 7 d / 30 d | **0** / 144 / 271 | `time_updated` windowed counts |
| Laptop newest `time_updated` | 2026-10-30 18:07:22 | `max(time_updated)` |
| Second opencode store | `~/.opencode/opencode.db` = 0 bytes, no tables, dated Oct 21 | direct read; ruled out as a hiding place |
| Mini session rows / last-24-h / newest | 169 / **0** / **2026-10-17 04:32:23** | read-only sqlite over ssh; mini clock confirmed `2026-10-31 20:50 IST`, so the 14-day gap is real |
| `ORG-*`, `%ceo%`, `%lead-%` titles | **0 rows on both hosts** | `like` queries against the full session table |
| The ten session IDs published as evidence in `~/OpenAlice_10K_Orchestration/discovery-wave1.md` | **absent from both hosts**; the entire `ses_e71%` ID prefix range returns 0 rows | per-ID lookups; control lookup on a known-real id (`ses_eed23270…` → "Hu work status") returned its title, proving the query has teeth |
| Live Qoder sessions | 3 of 50, all titled `粘贴的文本.txt` — four concurrent attempts at this same prompt | `list_chat_sessions` |
| opencode processes on the mini | **54**, unstable (one method returned 297 in the same minute) | `ps`-based; see §3.1 |
| Real opencode service, laptop | exactly 1: `~/.opencode/bin/opencode serve --service`, up 23 h, 533 MB RSS | `ps` with an argv filter |
| `openalice-fleet` position | `df02580`, **10 ahead / 0 behind `origin/main`** | `git rev-list --left-right --count` after fetch |
| `openalice-fleet` untracked | `ORCHESTRATION_DISCOVERY_2026-10-31.md`, `coordination/`, `fleet-worktrees/` | `git status --porcelain` |
| `~/src/openalice-fleet` | `c205bed`, verified a **strict ancestor** of `df02580` → genuinely stale | `git merge-base --is-ancestor` |
| `office-hud/` in fleet | 362 tracked files, no nested `.git` | `git ls-files` |
| One worktree of the fleet repo | 87–285 MB; three carry their own `office-hud/node_modules` | `du -sh` |
| Free disk | **45 GiB** on `/System/Volumes/Data`, 78 % used | `df -h` |
| Credentials available | 12 keys in `~/.env` (NVIDIA ×4, Groq, Cerebras, Gemini, OpenRouter, DeepInfra, Cloudflare ×2); `LLM_PROVIDER=groq`. **No `OPENAI_*` key exists anywhere.** | key names only, values never read |
| Toolchain | node 22.22.3, npm 10.9.8, pnpm 11.5.2, python 3.14.5, uv 0.11.19, docker 29.6.2, postgres 15.18, redis 8.10, git 2.50.1, gh 2.96.0 | `--version` per binary |
| `gh` API identity vs git author identity | `gh` is authenticated as **`krisharyanagarwal-dev`**; commits are authored as **`goodwearrinfo-aryan`**; fleet remote is `krisharyanagarwal-dev`, `openalice-ui` remote is `goodwearrinfo-aryan` | `gh api user`, `git config`, `git remote get-url` |

### 3.1 Two numbers this design refuses to build on

`pgrep -f opencode | wc -l` returned **297** once and **54** a minute later on the same host. One output line (`done`) was truncated mid-pipe and counted as a process. Separately, `discovery-wave1.md`'s "Active OpenCode sessions: 100+" is a count of database rows, not of running sessions — 70,705 of those rows are a September batch.

**Consequence for the design:** process counts and row counts are not rosters. Section 11 requires every adapter to return *session identifiers it can re-address*, each stamped with the probe that produced it. Nothing else populates a slot.

---

## 4. Architecture

```
                      Next.js dashboard (read projections + gated control routes)
                                    |
                                    | HTTPS + WebSocket/SSE
                                    v
   +=================== Task-State Authority (one FastAPI process) ===================+
   +  transition()      sole writer          state_edges()   machine-readable lifecycle +
   +  roles            10K catalogue rows    worker_slots    measured, disposable      +
   +  leases           TTL + holder          fencing tokens  monotonic per task        +
   +  worktrees        engine-owned pool     merge_queue     deterministic order       +
   +  outbox_events    same txn as commit    audit_events    append-only, redacted     +
   +===============================+===================================+==============+
                                   |                                     |
                          Postgres 15 (durable, sole truth)     Adapter probes
                                                                    |
                              +-------------------+-----------------+------------------+
                              | Qoder sessions    | opencode serve/DB | Agent tool   |
                              | (list_chat_sessions)|                | (subagents)   |
                              +-------------------+-----------------+------------------+
```

One authority, one database, no second writer. The dashboard is a client of the authority, never a peer of it. If the authority is unreachable, the dashboard shows the last projection stamped with its age and refuses to dispatch; it does not become a fallback.

---

## 5. Data model

Only the tables that carry design decisions are listed.

```sql
prompts(id pk, source, submitted_at, actor, status, trace_id)                    -- §15 traceability anchor

roles(id pk, name, capability_profile jsonb, profile_version int, status,
      retired_at, tombstone_at, UNIQUE(id, profile_version))                     -- 10K catalogue rows

worker_slots(id pk, adapter, external_ref, state,                                  -- state ∈ LIVE|IDLE|LOST|MOCK
             verified_at, last_seen_at, probe_run_id)                              -- verified_at set ONLY by §11

tasks(id pk, prompt_id fk→prompts, role_id fk→roles, objective, priority,
      repo, base_commit,                                                          -- pinned SHA, never a branch name
      allowed_paths jsonb, prohibited_paths jsonb,
      allowed_ops jsonb, prohibited_ops jsonb,
      acceptance jsonb, verification jsonb,
      limits jsonb,                                                               -- wall_clock, provider_calls, cpu
      state, fencing_token bigint, assigned_slot_id fk→worker_slots NULL,
      worktree_id fk→worktrees NULL,
      created_at, updated_at, completed_at)

state_edges(from_state, to_state, requires_evidence bool, retryable bool)         -- data, not code

leases(task_id fk, slot_id fk, fencing_token, acquired_at, expires_at, renewed_at,
       released_at, released_reason)

worktrees(id pk, repo, base_commit, path, state,                                  -- FREE|ALLOCATED|REAPED|QUARANTINED
          leased_to_task fk→tasks NULL, allocated_at, reaped_at, size_bytes)

merge_queue(seq bigserial, task_id fk, worktree_id fk, state, attempted_at, outcome)

task_evidence(id pk, task_id fk, produced_by_slot, produced_at, kind,              -- diff|test-log|artifact|probe
              payload_ref, sha256, verdict, verified_by, verified_at)

outbox_events(id bigserial, prompt_id, task_id, event_type, payload jsonb,
              emitted_at, published_at, dedupe_key unique)

audit_events(id bigserial, at, actor, action, target, before_state, after_state,
             fencing_token, redacted_payload jsonb, outcome)                      -- append-only, no UPDATE/DELETE grants
```

Two invariants enforced by the schema, not by application code:

1. `tasks.state` is `CHECK`-constrained to the set appearing in `state_edges`, so an undocumented state cannot be written.
2. `worker_slots.verified_at IS NOT NULL AND adapter <> 'mock'` is required by the `QUEUED` guard in §6. A mock slot therefore cannot enter the machine, structurally.

---

## 6. Transition authority and the state machine

Every write to `tasks.state` passes through exactly one SQL function:

```sql
task_transition(task_id, to_state, fencing_token, evidence, actor) → (ok, reason)
```

Its core is a **conditional** UPDATE — the guard is inside the statement, so there is no read-modify-write window to race:

```sql
UPDATE tasks t SET state = to_state, updated_at = now()
 WHERE t.id = task_id
   AND t.fencing_token = fencing_token
   AND EXISTS (SELECT 1 FROM state_edges e
                WHERE e.from_state = t.state AND e.to_state = to_state)
   AND (to_state <> 'QUEUED' OR (SELECT verified_at IS NOT NULL AND adapter <> 'mock'
                                  FROM worker_slots s WHERE s.id = t.assigned_slot_id))
RETURNING true;
```

Zero rows returned is a **rejection**, not a no-op: the caller gets `ok=false` with a reason code, and the attempt is written to `audit_events` including the token that failed. This is the mechanism that makes the attached prompt's "never pretend a session is active when it is not" enforceable rather than aspirational.

Lifecycle per attached §5: `CREATED → PLANNED → APPROVED → QUEUED → RUNNING → VERIFYING → COMPLETED`, plus `BLOCKED`, `FAILED`, `CANCELLED`, `QUARANTINED`. The edges are rows in `state_edges`, so the machine is auditable data and a new edge is an insert rather than a deploy. `retryable` on the edge row is what makes "retries only when policy permits" (§5) checkable at the point of transition instead of in a caller's good intentions.

---

## 7. Fencing tokens and leases

- `fencing_token` is monotonic per task, drawn from a task-scoped sequence and **bumped on every lease grant**. A holder presents it on claim, on each progress write, and at commit. A stale token matches zero rows in §6 and is therefore inert.
- Lease acquisition is one transaction: `SELECT … FOR UPDATE SKIP LOCKED` on the candidate task, then the `leases` insert, then the token bump. Two racers cannot both hold the same lease; the loser sees no row.
- A reaper sweeps `expires_at < now()`, revokes the lease, bumps the token, and drives `RUNNING → BLOCKED` where the edge is `retryable`, else `QUARANTINED`. The zombie-process case from §3.1 is fenced here: an abandoned holder's next write fails on token mismatch.
- Lease TTL, renewal window and reaper interval come from policy config, never literals, per attached §3 "do not hardcode".

## 8. Roles versus workers — the 10K model, bounded by arithmetic

The owner direction was "10k agents". Taken as 10,000 simultaneous processes it is not achievable on this host, and the ceiling is arithmetic rather than opinion: one fleet-repo worktree measures **87–285 MB** against **45 GiB** free, so 10,000 concurrent checkouts would need roughly **1.5 TB** — about 30× the available space, before toolchains, on a volume already 78 % full. The realistic bound is a few hundred bare worktrees and, once per-worktree `node_modules` and headroom are counted, **a pool in the dozens**.

This is the 10K design's own distinction, now proven locally: registration is not execution.

- `roles` holds up to 10,000 versioned capability profiles — ordinary rows. 10K rows is nothing to Postgres.
- `worker_slots` holds the small measured set of executors an adapter can actually re-address right now.
- The attached §4's twenty named responsibilities become twenty **role rows**, `UNFILLED` until a probe verifies a slot. They are never seeded from a wish-list, which is the failure mode that produced four blocked registries on 2026-10-31.
- Admission is bounded by an explicit envelope — worktree pool watermarks, provider concurrency, wall-clock budget — so the queue slows at the ceiling instead of discovering it mid-run.

## 9. Isolation by construction — no human intervention

The owner required file-contention enforcement without a person in the loop. Excluding two tasks from one shared file cannot deliver that honestly: hashed path ranges collide falsely and cannot express prefix containment, and `ltree` has no `&&`-capable gist opclass for an exclusion constraint. So the engine does not share files in the first place.

- Each task receives its **own ephemeral worktree** from the engine-owned pool, checked out at the task's pinned `base_commit`. Never a branch name, never a moving ref — the fleet is 10 commits ahead of `origin/main` and `origin/main` has been observed to move within minutes.
- Concurrent modification is then **impossible by construction**, so the path-exclusion problem disappears rather than shipping degraded.
- Enforcement moves to merge-back, with a boundary that keeps "no human in the loop" and "no automatic merge" from contradicting each other. `merge_queue` applies accepted evidence, in deterministic order (`base_commit`, then priority, then `seq`), onto **an engine-owned integration branch inside an engine-allocated integration worktree**. That is Class B: local, reversible, and shared with nobody. **Landing it on any canonical branch is Class C and stays blocked pending human review**, which is what attached §7 requires.
- A conflict fences the task: lease revoked, token bumped, output `QUARANTINED`, `audit_events` records why, and the queue advances to the next item. **No escalation to a human, and no merge into any ref outside the engine's own integration worktree** — those are different guarantees and the design keeps them separate.
- Pool hygiene is a first-class concern, not cleanup: high/low watermarks gate admission, reaped worktrees are reclaimed and their size recorded, and `node_modules` is shared through the pnpm store rather than copied per worktree — the 285 MB case is three duplicated `office-hud/node_modules` trees.
- A task's `allowed_paths`/`prohibited_paths` (§5) are still validated at `VERIFYING` against the produced diff, so out-of-scope work is detected even inside its own worktree.

## 10. Outbox, projections, and traceability

`task_transition` writes `tasks`, `outbox_events`, and `audit_events` in one transaction. A publisher drains `outbox_events` to WebSocket/SSE and to the read projection; consumers dedupe on `dedupe_key`. No queue message is authoritative — the queue is a notification, never a source of state.

Because `prompts.id` is carried on tasks, leases, evidence, outbox and audit rows, "trace a user prompt through every task, session, tool invocation and final result" (attached §11) is one join. That is the property whose absence made today's four reports mutually unreadable.

## 11. Adapters and roster honesty

Four adapters are real today; each declares its capability envelope (`read` / `write` / `execute` / `test` / `respond-only`) per attached §6, and each is separately approved before it writes anything.

| Adapter | Discovery mechanism | What it can honestly claim |
|---|---|---|
| Qoder | `list_chat_sessions` | Real IDs + `runtimeState`. Verified 3 live / 47 cold on 2026-10-31. |
| opencode | `serve --service` API, falling back to the session DB read-only | Row counts are **not** sessions; a slot needs a re-addressable ID. |
| Agent tool | In-session dispatch | Subagent runs, verifiable via the documented `subagents/*.jsonl` artifacts. |
| Mini (`a@macmini`) | Read-only ssh | 169 lifetime rows, nothing live in 14 days. Needs its own approval before use. |

Rules that make §3.1's confusion impossible to repeat:

1. `worker_slots.verified_at` is set **only** by a probe run that returned that identifier, and `probe_run_id` records which.
2. A mock adapter exists for tests and stamps `adapter='mock'`; the §6 guard blocks it from `QUEUED`, and the UI renders mock rows as simulated. **Simulated cannot become implemented.**
3. Adapters report failure as `UNKNOWN`, never as "zero sessions" — the distinction that makes a dead probe visible instead of healthy-looking.

## 12. Reasoning provider and secrets

`groq` is configured and key-backed today; **no OpenAI credential exists** — `~/.env` holds 12 keys, none of them `OPENAI_*`, and `LLM_PROVIDER=groq`. The attached prompt's own §3 anticipates this: a ChatGPT subscription is not API access, and credentials and billing are configured separately.

- The orchestrator talks to a provider-agnostic `ReasoningAdapter`. Model, context limit, timeout and budget are server-side config; no model name is a literal anywhere in the tree.
- **DoD #3 ("the configured OpenAI model returns a response") is BLOCKED on a credential only you can create.** The engine is built and tested against the mock provider; the OpenAI-backed test is *pending*, and is never reported as passed.
- Keys are read from the process environment at the adapter boundary, never from browser storage, never in a commit, and redacted before reaching `audit_events`, task payloads, logs or reports. §17 includes a redaction test that re-scans the emitted rows rather than trusting the redactor.
- Worker inference stays NVIDIA-only. Nothing in this project changes fleet routing, and the dashboard holds no trading credential.

## 13. Action classes and what the engine may self-serve

| Class | Meaning | v1 behaviour |
|---|---|---|
| A | Read-only | Allowed freely; every call audited. |
| B | Reversible local engineering inside a worktree the engine itself allocated — task worktrees and the integration worktree alike | **Self-served** — this is the "no human intervention" mandate, and it is confined to disposable checkouts the engine created and no other consumer reads. |
| C | Destructive or broad | Blocked. No automatic merge, reset, clean, or delete outside the pool. |
| D | External or paid side effect | Blocked, including any live provider call that spends money. |
| E | Protected infrastructure or trading | Blocked. No HUD, launchd, trading-config, or credential path exists in this codebase. |

Approval, where required, is bound to the exact action **and its content and target**, not to a path or a role — a one-time approval must not silently become a standing licence. A general instruction is never blanket authorization, and a menu selection authorizes the scope it was shown, nothing beyond it.

## 14. Dashboard surface in v1

Three surfaces, not fourteen, because the other eleven would render empty tables over an empty roster:

1. **Loop** — current state of the authority: queue depth, worktree pool watermarks, leases held, transitions per minute, provider availability, and an explicit `last projection update` age so staleness is visible.
2. **Prompt trace** — one prompt expanded through its plan, tasks, slots, leases, evidence, verdicts and audit rows. The §11 traceability requirement made checkable by a person.
3. **Roster** — role catalogue against verified slots, with mock and unknown rows visually distinct from live ones.

Real-time via SSE from the outbox; polling only as the documented fallback, and the transport is named in the UI rather than implied.

## 15. Observability and audit

Structured JSON logs with `prompt_id`/`task_id` correlation, never a secret. `audit_events` is append-only and the application's DB role has no `UPDATE`/`DELETE` on it. Provider latency, token consumption, estimated cost, failure counts, retry counts, queue depth and pool occupancy come from authoritative rows rather than a worker's self-report. Anything unmeasured reads `UNKNOWN` — never zero, never green.

## 16. Security

Loopback bind by default; authentication before any control route; the dashboard is not reachable without a session. Provider keys stay server-side. Artifact quarantine for anything a validator rejects. Task payload size and path shape are validated at the boundary — the fleet's own history includes a shell pathspec quirk (`"$c:tests/x"` silently applying `:t`) that is treated as hostile input, not as a path. No path from the dashboard to trading execution, HUD deployment or launchd, and §17 includes a test that proves those routes are *absent* rather than merely unused.

## 17. Testing — and proving the tests can fail

The engine's correctness is its concurrency control, so a suite of happy-path unit tests would be decoration. Required, against a real Postgres, never SQLite (SQLite cannot exercise `SKIP LOCKED`, row locks, or the constraint semantics §5 depends on):

1. **Two-writer race.** 20 parallel connections attempt the same transition; exactly one returns `ok=true`; 19 audited rejections; final state is the single legal successor.
2. **Fencing.** Replay a stale token → zero rows updated → `REJECTED` + audit row.
3. **Lease expiry** on an injected clock → token bumped, holder's next write inert, `RUNNING → BLOCKED` on a `retryable` edge, `QUARANTINED` on a non-retryable one.
4. **Every illegal edge** in the state cross-product is rejected; the test enumerates edges rather than spot-checking them.
5. **Merge-back conflict** → the losing task is quarantined, the queue advances, and **no write lands on any ref outside the engine's own integration worktree** — asserted by enumerating refs before and after, so a stray commit to a shared branch fails the test rather than passing unnoticed.
6. **Restart recovery.** Kill the authority mid-queue, restart; the outbox drains exactly once, no duplicate commit, no orphan lease survives its TTL.
7. **Cancellation** at each state, with a late worker result fenced by §7.
8. **Approval enforcement.** Class C/D/E routes are absent at the router level, asserted by a scan that proves non-vacuous coverage.
9. **Secret redaction.** Feed a synthetic key through prompt → task → audit → report and re-scan the *emitted* rows, not the inputs.
10. **Roster honesty.** A mock slot cannot reach `QUEUED`; an adapter probe failure yields `UNKNOWN`, not an empty list.
11. **Mock provider only** for the whole suite — no spend, no external call, per attached §12.
12. **Teeth verification.** For each of 1–10, inject the defect it guards against (drop the fencing predicate, delete an edge row, disable the reaper) and confirm that specific test goes red, then revert. A test that stays green under its own mutant is reported as decoration and fixed, not counted as coverage.

Test database via docker compose (docker 29.6.2 present) for reproducibility; development against Homebrew Postgres 15.18.

## 18. Deviations from attached §8, with reasons

| §8 asked | Adopted | Why |
|---|---|---|
| Redis for transient queues "if justified" | **Omitted in v1** | §5's own rule is one task-state truth. The transactional outbox plus `SKIP LOCKED` already gives durable claims; Redis would add a second coordination source that §5 forbids. Revisit only when measured queue depth justifies it. |
| Containerized services | **Tests containerized, dev native** | Concurrency tests need a reproducible Postgres; day-to-day dev does not need a container cycle. Homebrew 15.18 is already installed. |
| PostgreSQL durable state | **Kept** | It is the only component here that can enforce single-writer semantics under real races. |
| — | **Backend pinned to Python 3.12/3.13 via `uv`, not the system 3.14.5** | Native wheels (`pydantic-core`) on 3.14 are still thin; a missing wheel mid-build is a stall, and `uv` is already installed to make the pin cheap. |
| §2's fourteen nav pages | **Three pages in v1** | Eleven pages over an empty roster display fabricated emptiness. §14's three pages each prove something. |
| Isolated project or worktree, §7 | **New standalone repo** | `~/openalice-universal-command-center` is a 3-file stub and a four-way contention point; `~/openalice-fleet` is canonical and must stay preserved. Nothing is reused or overwritten. |

## 19. Decisions still owned by you

These are external decisions, not gaps in this design; each is written so one answer closes it.

1. **OpenAI credential.** DoD #3 needs an API key and separate billing. Is one being created, and at what monthly budget cap? Until then the honest status of items 3 and 12 is *pending*, not *done*.
2. **OpenRouter policy.** Attached §6 forbids OpenRouter for worker workloads while `OPENROUTER_API_KEY` sits live in `~/.env`. Does the prohibition extend to *dashboard* reasoning, and should the key remain in the fleet `.env`?
3. **HUD provenance.** 10K §16 is unresolved: `office-hud/` is 362 tracked files inside `openalice-fleet`, while `:4747` serves from `fleet-worktrees/office-deploy` at a detached `a33d621`. Which revision is canonical source, and who approves changes? This design touches neither.
4. **Remote and push.** No remote is configured on this repo. The `gh` API identity is `krisharyanagarwal-dev` while commits are authored as `goodwearrinfo-aryan`, and fleet and `openalice-ui` live under different accounts. Which account, which repo name, and is pushing this work permitted at all?
5. **The unpushed 10 commits and the sibling drop in the fleet repo.** `openalice-fleet` is 10 ahead of `origin/main` with `coordination/`, `ORCHESTRATION_DISCOVERY_2026-10-31.md` and `fleet-worktrees/` untracked inside it. Those three untracked items came from the sessions that ran this prompt before me; they are being preserved, not touched. Do you want them pushed, moved out, or left?

## 20. Definition of done, mapped honestly

| Attached §14 item | Status after v1 | Evidence that decides it |
|---|---|---|
| 1 dashboard opens | **Implemented + locally tested** | browser check on a real port |
| 2 prompt submits | **Implemented + integration tested** | row in `prompts` + trace join |
| 3 OpenAI model responds | **BLOCKED — no credential** | refused until a real response is captured |
| 4 conversations persist | **Implemented + integration tested** | restart, re-read |
| 5 orchestrator makes structured tasks | **Implemented, mock provider** | schema-valid plan rows |
| 6 tasks assigned to *available* sessions | **UNVERIFIED — no live roster** | needs a probe-verified slot; §3 proves none exists today |
| 7 live session/task status | **Implemented + locally tested** | SSE from the outbox |
| 8 results consolidated | **Implemented** | evidence rows + verdict |
| 9 approval gates block | **Implemented + integration tested** | §17.8 router-absence scan |
| 10 audit logs show what happened | **Implemented** | append-only, `UPDATE`/`DELETE` revoked |
| 11 provider failure handled safely | **Implemented + integration tested** | §17.3, §17.6 |
| 12 automated tests demonstrate it | **Only with §17.12 teeth verification passed** | mutation log per test |

Vocabulary is the attached §14's own: *implemented / locally tested / integration tested / human reviewed / deployed / production verified.* Items 3 and 6 are reported as blocked and unverified rather than quietly promoted, and nothing is called deployed — v1 is local only.

## 21. State this design leaves untouched

- `~/openalice-universal-command-center` — the 3-file stub, left exactly as found.
- `~/openalice-fleet` — canonical. Its three untracked items preserved. No file written, nothing staged, no push, no `clean`.
- `~/openalice-ui`, `~/src/openalice-fleet`, `~/fleet-worktrees/*`, `~/openalice-10k-*`, `~/OpenAlice_10K_Orchestration` — untouched.
- The live HUD on `:4747`, all launchd services, and every trading path.
- All running agent sessions, including the three other sessions working on this same prompt. Nothing was killed, merged, prompted or keystroked.
