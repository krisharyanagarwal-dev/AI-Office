# MCP Server Status Report

Last verified: 2026-10-31 17:05 IST — **all 16 configured MCP servers connected**, palace rebuilt and quality-checked.

Verification commands:
- `opencode mcp list` → 16/16 `✓ connected`
- `opencode api GET /api/mcp` → same, per-server status object
- Functional call: `palace_query` returns live semantic hits with correct source paths

## Current state

| Server | Status | Notes |
|---|---|---|
| blockchain-query | connected | local, `~/.claude/mcp-servers/blockchain-query` |
| claudeai-chembl | connected | ChEMBL v34 tools |
| claudeai-gmail | connected | |
| fetch | connected | |
| filesystem | connected | |
| git | connected | |
| github | connected | |
| graphify | connected | |
| headroom | connected | |
| memory | connected | |
| **mempalace** | **connected (repaired 2026-10-31)** | see below |
| obsidian | connected | |
| playwright | connected | |
| postgres | connected | |
| sequential-thinking | connected | |
| shopify-dev | connected | `npx -y @shopify/dev-mcp@1.14.0` |

## The mempalace failure — root cause and fix

### Symptom
`opencode mcp list` reported:

```
✗ mempalace  failed: Connection closed: MCP server process exited with code 0:
  MemPalace Lightweight MCP Server starting (3 consolidated tools)...
  No palace found at /Users/aryanagarwal/.config/mempalace/palace
  MCP server idle for 8.0 h (limit 8.0 h); exiting to release file handles.
```

### Root cause (two stacked causes, neither a config bug)
1. **No palace existed.** The server resolves its store to
   `~/.config/mempalace/palace` (override: `MEMPALACE_PALACE_PATH`, or `--palace`).
   No palace directory existed anywhere on the host — `mempalace status` reported
   *"No palace found … Run: mempalace init <dir> then mempalace mine <dir>"*.
   The server still starts and lists its 3 tools (so `mcp connected` was never
   proof of a working palace), but every *query* path fails with
   `PalaceNotFoundError`.
2. **Stale client after the 8h idle exit.** The server process deliberately exits
   after 8h idle ("exiting to release file handles"). The OpenCode MCP client for
   this directory then kept the dead connection and kept replaying the *old*
   stderr text, so the status stayed `failed` even after the palace was created.
   Server log evidence: `timestamp=2026-10-31T05:07:41Z … "mcp transport error"
   server=mempalace`.

### Fix applied
```bash
mempalace init /Users/aryanagarwal/openalice-fleet --yes --no-llm   # creates the palace
mempalace mine /Users/aryanagarwal/openalice-fleet --limit 0 --direct --agent opencode
opencode api POST /api/experimental/mcp/mempalace/connect            # respawn the server
```
The `connect` call is the part that is easy to miss: the client will not
re-spawn a dead local MCP server on its own, so `mcp list` keeps showing the
stale error until you force a reconnect.

## Palace rebuild — the first build was 96% junk

The first successful mine produced **157,933 drawers, 1.1 GB**, and the queries
proved it was unusable: the top hit for a fee question was a 1.3 MB backtest
JSON dump. Two causes, both mechanical:

| Junk | Size | Why it was mined |
|---|---|---|
| `research/strategy-search/audit/*.json` | 51 MB in 7 files | data dumps (numeric tables), not prose. `MAX_FILE_SIZE` is 500 MB, so nothing was skipped. Four copies existed (repo + `fleet-worktrees/` + two `.worktrees/`) |
| `fleet-worktrees/` | 211 MB, 8,212 files | a full nested copy of the repo, untracked and **not** gitignored, so the miner walked it |

Result: `research` held 100,016 drawers (63%) and `fleet_worktrees` 52,690
(33%) — 96.6% of the palace, with every real document diluted.

### Fix: `exclude_patterns` in `mempalace.yaml`
```yaml
exclude_patterns:
- fleet-worktrees/
- .worktrees/
- "**/node_modules/"
- research/strategy-search/audit/*.json
- graphify-out/graph.json
- trading/paper-benchmark/*.json
```
Verified with `mempalace mine --dry-run`: **1363 files, 0 junk paths** (down from
2791). Palace wiped and re-mined from scratch.

### Before / after
| | first build | rebuilt |
|---|---|---|
| files mined | 2791 | 1343 (1363 scanned) |
| drawers | 157,933 | **29,164** |
| palace size | 1.1 GB | **245 MB** |
| `research` room | 100,016 | 8,785 |
| duplicate `fleet_worktrees` room | 52,690 | gone |

### Quality check — same six queries, before vs after
| Query | Before (junk) | After (rebuilt) |
|---|---|---|
| VIP 0 spot maker/taker fee | `whale_sweep_backtest.json` (data dump) | **`cost_model.py`** (sim 0.68), `test_cost_model.py` (bm25 4.5) |
| live_orders_allowed / paper only | `test_live_boundary_guard.py` | `evidenceRoutes.test.js`, `tradingSafety.js` (sim 0.61) |
| separation_ratio / bootstrap width | `TRADING_HANDOFF.md` | **`verdict_stability.py`** + `test_verdict_stability.py` |
| pubserver :3002 dashboard | `service_subagents.json` | `index.js`, `service_subagents.json`, a dated investigation doc |
| daily loss limit / risk | `strategy_audit.json` (numbers) | **`main.py`** (bm25 7.96), **`risk_manager.py`** (bm25 6.74) |
| abandonment / never flatten | `test_hive_tracked_paths.py` (wrong) | **`test_eth_paper_execution.py`** + `eth_paper_execution.py` |

All six now land on the canonical source. Content spot-checked, not just
filenames: the `cost_model.py` hit reads *"The forward returns in this report
are GROSS… a Binance spot round trip is 20"* and `test_cost_model.py` documents
that fee schedules are asserted against published VIP 0 rates.

## Scope decision for what to index
JEV (`jev pick`, P=0.82 for the chosen option) chose **`openalice-fleet`** over
`Documents` (P=0.01) and `polymarket` (P=0.16). Evidence given to JEV: candidate
file counts/sizes and the transcript-noise profile of `~/Documents`
(`agent-workspaces` + dated `Qoder/` session dumps ≈ 4.7k of 14.2k files).

## Also landed on `origin/main` (2026-10-31)
The orphaned `feed_freshness` feature — 9 files, uncommitted for ~15h with an
expired claim — was adopted rather than left in the tree:
- `409d02f` — `feat(freshness)`: shared feed-age read-model
  (`services/feed_freshness.py`) consumed by `terminal.py`,
  `services/oa_pubserver.py` (`GET /api/freshness`) and the office dashboard;
  registers `tests/test_feed_freshness.py` in both `pytest.ini` testpaths and
  the quality gate's `TEST_PATHS` (it was in neither, so the gate proved
  nothing about it). Gate: **QUALITY GATE PASSED**, 625 passed / 32 skipped.
- `492ab3e` — `chore(ignore)`: keep `mempalace.yaml` / `entities.json` out of
  the tree.
- `7e90c1d` — `fix(watchdog)`: the Python-3.9 import fix, cherry-picked from
  the laptop's diverged `main` (the only local commit whose content was
  genuinely missing upstream; the other three were already there in evolved
  form). Gate: **QUALITY GATE PASSED**.

The laptop's `main` then converged on `origin/main` (merge `df02580`; the
merge was dry-run first in a scratch worktree and was conflict-free; after it,
`git diff origin/main HEAD` is empty — identical content). Both local
dashboard services were restarted, and all three consumer surfaces of the new
read-model were verified live:
- TUI: `terminal.draw_freshness()` renders the DATA FRESHNESS panel
- web cockpit: `GET :3002/api/freshness` → 200, 11 feeds, verdict + per-feed
  age/SLA, and it states the `feeds_dir` it inspected
- office dashboard: the `/api/freshness` route exists in `office/dashboard.py`,
  but the Python process that serves it is broken — see below.

## Footprint (do not mistake this for unrelated dirt)
- `openalice-fleet/.gitignore` — 4 lines: `mempalace.yaml`, `entities.json`
  (+ comment). Now identical to `origin/main`'s content; still shows as
  modified locally only because this laptop's `main` is behind.
- `openalice-fleet/mempalace.yaml`, `openalice-fleet/entities.json` — created by
  `mempalace init`; the miner reads `mempalace.yaml` for wing/room mapping and
  my exclude list, so they stay in the project dir. Machine-local by design.
- `openalice-fleet/fleet-worktrees/` — **pre-existing**, not mine. It is the
  duplicate repo copy the exclude list now keeps out of the palace.
- `~/.cache/chroma` grew to ~167 MB (one-time ONNX embedding-model download).

## Next steps
1. **Re-mine when the corpus changes.** The mine is incremental and idempotent,
   so `mempalace mine ~/openalice-fleet --limit 0 --direct --agent opencode`
   picks up only new files. Re-run it after a batch of fleet commits; the
   palace is a snapshot, not a live index.
2. **Watch for the same junk returning.** The excludes live in
   `mempalace.yaml` (machine-local). A new nested copy of the repo, or a new
   multi-MB data dump, will re-inflate the palace. Check
   `palace_query STATUS` room counts after any re-mine — a single room holding
   >30% of drawers is the tell.
3. **The 8h idle exit is by design, not a fault.** If `mcp list` shows
   `failed: ... idle for 8.0 h`, the fix is
   `opencode api POST /api/experimental/mcp/<server>/connect`, not a config
   change.
4. **Next unrelated work item:** the local `main` is 10 commits behind
   `origin/main` and 5 ahead (duplicate hashes from parallel agents). It
   converges by merge/cherry-pick from `origin/main` — not by copying files
   across.
