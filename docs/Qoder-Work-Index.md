# Qoder Work Index — 2026-10-18 18:31 IST (13:01Z)

Generated read-only from `list_chat_sessions` (2 pages, `nextCursor: null`), `git worktree list`,
`launchctl print`, `launchctl list`, plist inspection, and `du`. Nothing was moved, renamed,
archived or deleted. Cross-reference: fleet audit
[audit-20261018T130119Z.md](audit/reports/audit-20261018T130119Z.md).

## 1. Session inventory (app side)

| Measure | Value | How verified |
| --- | --- | --- |
| Unarchived sessions | **83** | 50 + 33 pages, `nextCursor: null` on page 2 |
| Archived sessions | **11** | `archived: true` page, `nextCursor: null` |
| Runtime `running` | **3** | `0bffb768` team working · `8408a520` Audit request (this one) · `975599de` work autonomusly |
| Runtime `ready` | **1** | `b36a16fe` General inquiry |
| Runtime `cold` | **79** | 83 − 3 − 1 |
| Unread | **6** | `0bffb768`, `d07dfaeb`, `995d6628`, `2c075f17`, `0af49c43`, `fbe599fa` |
| `pendingInteractionCount > 0` | **0** | every row returned 0 — nothing is waiting on a human answer |

Sessions grouped by `cwd`:

| cwd bucket | sessions | meaning |
| --- | --- | --- |
| `/Users/aryanagarwal` (home root) | 17 | ad-hoc/orchestrator chats, no project anchor |
| `/Users/aryanagarwal/openalice-fleet` | 7 | real repo-anchored fleet work |
| `Documents/Qoder/<date>/<8-hex>` | 59 unarchived + 11 archived = 70 | throwaway per-session scratch dirs |

## 2. Session cleanup plan (UI-only — no rename/archive API exists)

Do-not-archive under any circumstances (live runtime, would interrupt work):
`0bffb768` · `8408a520` (this session) · `975599de` · `b36a16fe`.

Archive candidates, by group (all `cold`, `pendingInteractionCount: 0`):

| Group | Count | Examples | Why safe to archive |
| --- | --- | --- | --- |
| Skill-draft chatter under `2026-10-08/6787bba2` | 12 | 拟定 Skill 创建方案 / 完善可复用 Skill / 技能更新草案 | repeated auto-titled runs on one task; the skill itself already shipped |
| Skill-draft chatter under `2026-10-11/47fc194e` | 4 | 请帮助我完善一个可复用的 Skill, 拟定技能方案 | same pattern, later date |
| "verify teams working" probes | 6 | `0bffb768`-adjacent: `ed6583ca`, `b332aadc`, `734b3c15`, `a6dff772`, `ce0c147e`, `2fb0b6ab` | one-off capability probes, conclusions already in memory |
| Greeting/empty titles | 4 | `08c2bbf1` "Casual greeting", `4aec026a` "Status check", `2fb0b6ab` "Requesting assistance", `83d486fa` "未命名会话" | no artifact |
| Superseded audit/verify runs | ~8 | `4069c121`, `953bb339`, `e31ea3f0`, `48ad9454` | replaced by the shipped `~/audit` automation |

Counts in this table are **hand-counted from the 94 returned rows**, not machine-derived — re-verify
each group in the UI before bulk-archiving. The §1 totals (83/11/3/1/79/6/0) are page-arithmetic and
checkable.

Keep by name (substantive, worth a real title): `2c075f17` (Teams working status),
`cc4952c0` (Agent Team smoke test), `256d0d0d` (Verify fleet system state),
`b94ad36f` (View and merge openalice), `d3d68c94` (**Add dashboard to sites — hosts a LIVE launchd
job**), `8d335b89` (**Notes Basic TA notebook translation — unique artifact**), `29a8bf5b`
(Git sync and local cleanup), `0645c80c` (Build autonomous audit automation),
`92513a86` (OPENALICE AUTONOMOUS ORCHESTRATOR), `3a6e7682` (Make Qoder an office tool).

Suggested naming rule going forward: `<repo/area> — <verb> <object>`, since auto-titles are what
makes this list unreadable.

## 3. Disk map

### `~/Documents/Qoder` — 1.8 GB, 101 session dirs, **90 empty**
Only 11 dirs hold anything; the heavy six:

| Dir | Size | Contents | Load-bearing? |
| --- | --- | --- | --- |
| `2026-10-10/e1fd231e` | 807 MB | `fleet`, `fleet1`…`fleet10` ≈ 80 MB each | check per-clone `git status` for unique work |
| `2026-10-09/29a8bf5b` | 254 MB | `hud_integration`, `hud_probe_base`, `hud_stage2` | **YES — 3 registered git worktrees** |
| `2026-10-17/d3d68c94` | 248 MB | 247 MB `node_modules`, `functions`, `dev/serve-local.mjs`, `PROVENANCE.md` | **YES — 2 LOADED launchd jobs run from here** (`com.aryan.fleet-console-server`, `…-snapshot`) |
| `2026-10-17/2f4be9e7` | 194 MB | `edge-probe-baseline` + `edge-probe-work` (97 MB each), `ledger-v2.patch.diff` | patch file is unique; probes are regenerable |
| `2026-10-08/6787bba2` | 175 MB | `hud-health-fix`, `fleet-alert`, `gate-liveness-patch`, `skill-drafts` | **YES — `hud-health-fix` is a registered worktree** |
| `2026-10-10/8d335b89` | 161 MB | `notes_basic.pdf` (14 MB), `pages` (16 MB), `signals` (121 MB) | **YES — `notes-signals-daily`/`-intraday` plists point at `signals/`** |

### Loose top-level work dirs
`fleet-worktrees` 1.1 GB · `oa-strat` 459 MB · `openalice-fleet` 381 MB · `fleet-workers` 118 MB ·
`github-opencode-archives` 88 MB · `openal-fleet` 236 KB · `qoder-session-floor` 648 KB ·
`workspace` 80 KB · `test-mcp-project` 124 KB.
`openalice-ui` is referenced by `com.aryan.openalice-tunnel` (plist present, not loaded).

### App state
`~/.qoder/projects` holds **101** path-keyed entries, **96** of which encode a
`Documents/Qoder/<date>/<id>` path. Project-scope memory is keyed by that path — moving a dir
orphans its memory silently.

## 4. Reorg move map (tiered, gated)

- **Tier A — zero risk, ~90 dirs:** remove the empty `Documents/Qoder/<date>/<id>` dirs. They contain
  no files; Qoder recreates a dir on demand.
- **Tier B — reclaimable after a uniqueness check, up to ~1.2 GB:** `e1fd231e/fleet*` clones and
  `2f4be9e7/edge-probe-*`. Requires per-clone `git status`/`stash list`/`log @{u}..HEAD` first — the
  audit already shows dirty trees elsewhere, so assume nothing is disposable until proven.
- **Tier C — do not move:** `d3d68c94` (live jobs), `8d335b89/signals` (plists), `6787bba2/hud-health-fix`
  and `29a8bf5b/hud_*` (4 worktrees), `openalice-ui` (plist), `openalice-fleet`,
  `github-opencode-archives`.
- **Consequence to accept before any move:** 96 path-keyed project/memory entries go stale; a moved
  worktree needs `git worktree repair`, and a moved launchd target needs a plist edit **plus**
  bootout/bootstrap to take effect.

Cheapest real win, in order: Tier A prune → Tier B after check → leave Tier C alone and index it
instead of moving it.

## 5. Qoder Projects / Issues — BLOCKED from this session

`mcp_list` for `issue`, `project`, `discussion` returns only Sites-plugin tools and `qoder_cron`; no
collaboration server is connected here, so I cannot create or manage Projects/Issues from this agent.
This is a session-tooling limit, not a claim that Qoder lacks the capability. Handover options: run
the request from a session that has collaboration tools, or let me draft issue titles + bodies from
§1–§4 for you to paste.

## 6. What "organizing" must not lose

The fleet audit found **9,697 commits in `github-opencode-archives` with no reachable off-machine
copy** (`ls-remote` → Repository not found; `origin/main` last advanced 2026-10-17 06:57 IST; active
`gh` account is `krisharyanagarwal-dev`, repo owner is the inactive `goodwearrinfo-aryan`). Every pane
archive the fleet produces is landing on this laptop only. Consolidating local directories is worth
far less than fixing that first.
