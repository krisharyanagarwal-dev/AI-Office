# OpenAlice — Merged Master Document

Generated: 2026-10-18 ~18:25 IST, by a Qoder agent session (`0bffb768`), from **every OpenAlice
markdown/txt document on this Mac**.

Source coverage, measured exactly: **146 documents / 963,799 bytes** scanned across the 8 requested
directories plus 11 home-level files (`.md`/`.txt`, excluding `node_modules/`, `.git/`,
`.pytest_cache/`). Of those, **140 documents / 913,735 bytes are in scope**; 6 home-level files carry 0
or 2 passing OpenAlice mentions and are excluded from the content merge (§12). Full provenance in §12;
duplicates and out-of-scope files are named, not silently dropped.

> **The corpus is live-moving, and this merge was overtaken mid-task.** A sibling session wrote
> `oa-strat/research/edge-probe-1h4h-20261012/drafts/prereg-draft-20261018.md` (**28,823 B, 18:31 IST**)
> *after* my first inventory, and touched `LOOP_LEDGER_NOTES.txt` at 18:01. That is why oa-strat measures
> 48 docs / 324,919 B here rather than the 47 / 296,096 of my 18:25 pass. The new draft **is merged** —
> §5.3 — but treat every count in §12 as a timestamped snapshot, not a property of the repo. Re-run §12.1
> before quoting these numbers.

**Safety:** this document contains **no credential values**. Secrets are referenced by file:line and
shape only. It was re-scanned after writing (§6.5).

**This file lives outside every git tree** so it does not dirty a repo. Nothing was committed.
No source document was modified or deleted.

---

## 1. How to read this document

Every merged statement carries one of five statuses. The point of the merge is *not* to make the
oldest claims look authoritative — these 135 files contradict each other constantly, and several were
proven false on disk.

| Status | Meaning |
|---|---|
| `LIVE` | Measured by me on 2026-10-18, on this host, this session |
| `AGREED` | Stated consistently by ≥2 independent source docs |
| `CONTRADICTED` | Two or more docs disagree; both values listed in §9 |
| `RETRACTED` | Doc claim tested against disk and found false — do not rely on it |
| `UNVERIFIED` | Only in one doc, no way to test it today; carried forward with its source |

`AGENTS.md` in the fleet repo is **not** ground truth: its interpreter table and its `origin` row are
both contradicted on disk (§9 C1, C7). Its one rule that *is* supported by git evidence — root `*.md`
files are historical snapshots, updates belong in commits (§12 of that file) — is honoured here: I
merged into this new file rather than rewriting any of them.

---

## 2. What OpenAlice is

Multi-host, multi-agent trading and control fleet on a MacBook Air (primary) + a Mac mini
(`As-Mac-mini`, over Tailscale/SSH):

- `services/free_harness.py` — free-model LLM harness, OpenAI/Anthropic-compatible bridges,
  provider routing by model prefix, failover chain.
- `trading_terminal/` — **paper/testnet** trading terminal. `live_orders_allowed=false`.
- `office-hud/` — local dashboard on `:4747`; Electron shell + web UI.
- `hive/` — terminal/session orchestration (deliberately unversioned).
- `oa_pubserver` — dashboards on `:3002`, password-gated.
- `research/` — strategy search, edge-probe studies, strat100.

`LIVE` repo root on this host: `/Users/aryanagarwal/openalice-fleet`. The path `/Users/a/trading/openalice-fleet`
that ~24 docs treat as canonical **does not exist on this machine** (`ls: /Users/a: No such file or
directory`) — it is the mini's layout, and every doc citing it as *the* repo root is describing the
other host (§9 C8).

> `RETRACTED` — `openalice-fleet/README.md` describes the repo as **"D2C Analytics for Shopify fashion
> brands"** with ngrok and an 8 GB RAM setup. That is a different project's README; it shares no
> content with the fleet. Source: `README.md` (14,325 B).

---

## 3. Live state snapshot — measured 2026-10-18, this session

Ports, from `lsof -nP -iTCP:<p> -sTCP:LISTEN`:

| Port | Documented owner | Live listeners | Verdict |
|---|---|---|---|
| 8080 | free_harness_server | **0** | `LIVE` **DOWN** — harness trio not running on the laptop |
| 8081 | ws_server | **0** | `LIVE` **DOWN** |
| 19593 | anthropic_bridge | 2 | `LIVE` up |
| 3002 | oa_pubserver | 1 | `LIVE` up (Python pid 1479; `/health` → 200 per fleet audit run) |
| 4747 | office-hud (local) | 2 | `LIVE` up — **local node**, not a tunnel |
| 4748 | SSH forward → mini's HUD | 2 | `LIVE` up (ssh pid 79480) — tunnel is healthy |
| 11434 | ollama `llama3.2:3b` | 1 | `LIVE` up |
| 8765 | trading-bot (paper) | **0** | `LIVE` **DOWN**; docs also disagree 8765 vs 8000 (§9 C5) |
| 20241 | cloudflared | **0** | `LIVE` **DOWN** — no local cloudflared process at all |

Repos `LIVE`:

- `openalice-fleet`: branch `feat/hud-service-lifecycle`, HEAD `b89f89a`, **2 modified files**
  (`office-hud/server/index.js`, `office-hud/server/truth_guard.py`, both mtime 16:16 — pre-existing,
  not written by anything in this session). `.git/config` contains **no** embedded credential.
- `oa-strat`: **broken worktree** — `.git` is a 68-byte pointer to a deleted worktree
  (`git rev-parse` → `fatal: not a git repository …/.git/worktrees/oa-strat`). Its `research/`
  cluster exists in **no other tree** and is tracked only by its own nested repo (last commit
  `b2e60f8` "research: add cycle 014", Oct 15), with `LOOP_SPEC.md` / `loop_cycle.py` /
  `LOOP_LEDGER.json` **modified uncommitted** and `APPLY_NOTES.md`, `drafts/`, `dashboard.html`
  **untracked**. ⇒ the newest research work is **not durable anywhere**.
- `openalice-fleet/research/` contains only `audit/`, `strat100/`, `strategy-search/` — **no
  edge-probe** (`LIVE`).

Interpreters `LIVE` — the inverse of what `AGENTS.md` states:

- `/usr/bin/python3` → `ModuleNotFoundError: No module named 'pytest'` (**not** the test interpreter).
- `/opt/homebrew/bin/python3` → **absent**.
- `/Library/Frameworks/Python.framework/Versions/3.14` → **exists**; `bin/run-tests.sh` self-selects a
  pytest-bearing python and the `tests/__pycache__` artifacts are `cpython-314-pytest-8.1.1`.
- `/Users/a/.venvs/openalice/bin/python` (used by `bin/run-fleet.sh:20`) → **absent on this host**.

launchd `LIVE`: `com.aryan.office-hud-server` is the loaded HUD label (docs also say
`com.aryan.office-hud`, and `services/README.md` invents five `com.openalice.*` labels that exist in
no plist). `com.aryan.openalice-manager` has a plist in `launchd/` but is **not installed or loaded** —
which is exactly why 8080/8081 are dark.

Agent Team `LIVE`: **no team has ever initialized on this machine** — no `team`/`squad` directory or
file under `~/.qoder` *or* `~/Library/Application Support`; `QODER_AGENT_TEAMS` unset;
`mcp_list keyword=team|squad` → 0. Details in §8.

---

## 4. Architecture and routing — merged doc claims

`AGREED` (`services/README.md:7-9`, `ARCHITECTURE.md:277-278`, `AGENTS.md:53-55`): harness 8080 /
ws_server 8081 / anthropic_bridge 19593 form **one supervised trio** under
`com.aryan.openalice-manager` running `scripts/run_24x7.py`. Do not re-enable the four per-service
`com.aryan.openalice-*-{free-harness,anthropic-bridge,ws-server}.disabled-superseded…` plists — they
fight over the same ports.

`AGREED` NIM failover chain (`CHANGES_SUMMARY.md:30-33`, `ARCHITECTURE.md:61-73`):
`550B → 120B → Lightning-30B → llama-3.1-70B`. Budgets: 60 s per request, 3× backoff at 1/2/4 s,
30 s Ollama bound (`ARCHITECTURE.md:84-91,118,146`).

`AGREED` routing: `call_model()` dispatches by prefix (`nim/`, `groq/`, `ollama/`, `openalice/…`).
`LOCALAI_ENABLED=1` is required for the LocalAI provider (off by default; LocalAI is **not installed**).
`.env.llm` at repo root holds provider keys, gitignored; keys must never be hardcoded.

`CONTRADICTED` LocalAI port: `ARCHITECTURE.md:41` says 8081 (which is ws_server) vs `AGENTS.md:103`
says 8090. `CONTRADICTED` mini address: `192.168.29.202` vs Tailscale `100.125.24.105` vs
`192.168.29.254` (§9 C3, C9).

`AGREED` trading legs: 4 indicator legs `candlesig / macdsig / coinrev / diverg`
(`FINAL_SUMMARY.md:84-87`, `TRANSFORMATION_UPDATE.md:68-71`, `LEGS_PNL_SUMMARY.md:13-16`); state at
`~/openalice/fleet-state/` incl. `book.json` (`LIVE` — that path exists).

---

## 5. Trading and research results — merged, with verdicts attached

Rule applied here: **a number never travels without its label.** Several of these docs quote a result
and separately reject it; stripping the rejection would manufacture a false claim.

### 5.1 edge-probe 1h/4h (`~/oa-strat/research/edge-probe-1h4h-20261012/`, 2026-10-12→10-18)

Locked 4h `sma200/b1` — 5y Binance spot BTC/ETH/BNB/SOL/XRP, 50/50 split, $10k books, 1x, 322 outer
trades (`FINAL_REPORT.md:12-15`, `results_tables.txt:19-35`, `sensitivity_ladder.txt:20-24`):

| Scenario | Net per trade |
|---|---|
| G0 gross | **+35.63 bp** |
| S3 (5 bp/side + 1 bp slip + funding) | **+21.43 bp** |
| S4 (severe 10 bp + 2 bp) | **+7.50 bp** |
| S2 | +25.38 bp |

**Documented verdict: `REJECTED`** — `FINAL_REPORT.md:5`, fails criteria A3/A4/A8. Per-symbol S3 net:
BTC −35.40, ETH +23.26, BNB −17.18, SOL +64.40, XRP +70.69. fold0 −111.81, **fold1 +172.09 = 143.3% of
all profit** (concentration failure). Worst fold drawdown −5.8%; exposure 9.0–11.6%; 26–47 entries
blocked per symbol. Train net at selection +51.8255 bp (`FROZEN_4H_CONFIG.json`).

Locked 1h `sma200/b2`, 1,124 trades (`FINAL_REPORT.md:9-11`): gross **−3.88**, net S3 **−17.84**,
−13.84 (S2), −31.84 (S4). **REJECT** (fails 6/8).

Confirmatory addendum `cycle_005` (`FINAL_REPORT.md:216-224`, all seven numbers confirmed exact in
`cycles/cycle_005.json`): pooled gross **−6.12 bp**, net S3 **−19.32**, ungated −11.79, 3/10 symbols
positive, share 0.824, HHI 0.695, worst rolling-182d drawdown **−66.2%**, **0 of 7** criteria passed.
Exploratory side: +8.18 / −5.35 / −29.93, 4/10, share 0.671, HHI 0.556, −57.5%, 2 of 7 (B1, B4).
Follow-the-leader detail: ungated S3 net +41.04 vs gated **−1.10**.

> `CONTRADICTED` — the same frozen config on the same confirmatory universe yields **two** answers:
> `cycle_005` gross −6.12 / net −19.32 (982 trades) vs `cycle_014` gross **−11.0** / net **−24.19**
> (976 trades). The report quotes only the Oct-12 read; the later artifact is **worse** and no document
> corrects it (§9 C1).

Amendments (`LOOP_SPEC.md`):
- **A2** (`:181-186`): 12 unseen symbols, 1,133 trades, gross +33.34, cost 11.74, net **+19.60**,
  7/12 positive, S5 fail (HHI 0.260). Status **candidate, NOT confirmed** — its S1–S4 are
  non-promotable because criteria were re-scored *after* the universe was seen, caused by
  `confirm_starvation.py` computing S2/S4 with `budget=None` (`:193-198`).
- **A3** (`:235-242`): 12 symbols, 853 trades / 977 days, gross **+70.36**, net **+52.90** at 5+2 bp,
  11/12 positive, HHI **0.216** vs a 0.20 limit → **hypothesis CLOSED**. No fourth universe permitted
  (`:226-227,244-245`); **49 symbols burnt** (`:304-313`).
- **Turnover starvation** (`:143-147`): raising cadence 1/week lifts gross in 21/30, 21/30, 22/30
  paired cells; 1/month +6.57 → 1/quarter −41.51.

Cost floor (`COST_FLOOR.md:28-29,41-45`): sma200 gross Δ −3.27 bp, improved in 14/30, t = −0.47;
1h **0 of 15** cells viable at 5 bp; **45/90 cells labelled `unviable_at_any_cost`**; portfolio
+21.23%/2.5y with −19.7% drawdown — explicitly labelled "a measurement fix, not a result".
The "4h gate carries information" finding was **withdrawn** (`FINAL_REPORT.md:209`) and independently
killed by the paired test (`COST_FLOOR.md:33-34`). Cycles 1–2's "promising" +22.18 / +8.81 were
**measurement artifacts** of the drawdown definition plus APTUSDT coverage (`LOOP_SPEC.md:231-235`).
The 5m line is all-negative: the SMA gate was a **turnover reducer only** (25/25 post-cost vs 11/25 at
zero cost). `1h ungated/b1` gross +13.27 / net +1.81 is exploratory and **explicitly not promotable**
(`FINAL_REPORT.md:124-127`).

Methodology guards — asserted vs demonstrated:

| Guard | Demonstrated by |
|---|---|
| Fill / signal lag (next-bar open, two-bar lag) | `test_results.txt:4` T3 — −94.991098%, 1720 trades, both engines |
| Look-ahead | T4 `:7-8` — 1,708 fills byte-identical under future corruption + must-DIFFER control |
| Fee / slippage / funding sign | T5–T7 `:9-15` |
| Data holes | one isolated missing 1h bar per symbol, T10 `:23-39`, artifact `gap_log.json` |
| Weekly entry budget | T8 `:16-19` — cap 0 → 0 trades, 10,464 blocked |
| Prereg tamper | `run_outer.py` aborts on SHA-256 mismatch of `PREREGISTRATION.md` (hash `adcb9c27…` in `FROZEN_4H_CONFIG.json`) — `UNVERIFIED` by me |
| Order-of-operations | G1–G4 in `test_confirm.py`; **G5–G9 exist only as spec in drafts, never run** |
| Real-bytes controls | `APPLY_NOTES.md:38-45` (D2c/D2e, T7b, D9) |

Known self-inflicted bugs recorded in the source, kept because they are the reason to distrust the
earlier numbers: `drafts/prereg-draft-20261016.md:169-173` — the unburntness gate reads the very draft
it validates, so all 12 candidates reported PRESENT, and a `{3,12}` regex silently swallowed OPUSDT
(49→60); `:179-187` two checks were vacuous until a zsh word-split / no-match bug was fixed.

### 5.2 Legacy claims — `UNVERIFIED`, and contradicted by §5.1

`services/README.md:64-68` claims live leg `scalp:rsi_meanrev_ls@5m` at **+$38,947 (+38.9%)**, win
rate 68.2% (101/148). **No methodology, no fee assumption, no date.** It directly contradicts the
research line's verdict on the same 5m leg — "loses roughly half its equity per quarter"
(`FINAL_REPORT.md:148-150`) (§9 C2).

`LEGS_PNL_SUMMARY.md:13-16` backtest PNL `candlesig 45.7 / macdsig 50.0 / coinrev 50.0 / diverg 56.8`
vs `:26-29` **live win rates 3.6% / 5.4% / 12.5% / 0.0%**; `:115-116` RR 5.0, `RISK_USD $100`.
`:167` admits "Schema access timed out". `:22` cites
`logs/legs_performance_20260910.log`, which is **not in `logs/`** (`RETRACTED`). These predate the
research by 17 days and **no source labels them accepted or rejected** — treat as unqualified history.

### 5.3 Open research design — funding-clock phase of the frozen 4h rule

Source: `~/oa-strat/research/edge-probe-1h4h-20261012/drafts/prereg-draft-20261018.md` (28,823 B,
written **2026-10-18 18:31 IST**, i.e. during this merge). Status, in the file's own words:
**DRAFT. Not declared. Not run. Nothing scored.** It computes no expectancy, pnl, sharpe, drawdown,
return or win-rate figure — the only numbers in it are definitional constants and filename counts.

- **Question:** does the frozen 4h rule's trade-level expectancy depend on whether its entry signal bar
  closes on a Binance USDT-M **funding-settlement boundary**? Settlement is every 8 h (00/08/16 UTC) and
  the 4h grid closes at 00/04/08/12/16/20, so exactly **3 of 6** closes coincide. Direction is
  pre-declared: boundary > non-boundary; the opposite sign is a **falsification**, not a rule to flip.
- **Deliberately not a re-ask** of the closed weekly-budget/starvation hypothesis (`LOOP_SPEC.md:226-227`
  forbids opening a fourth universe for that). It stratifies a read-only imported config on a question the
  closed hypothesis never asked, and a **Firewall** clause bars reporting any pass as evidence the frozen
  config generalises.
- **Universe:** 12 proposed Binance spot USDT mid-caps (2020-2021 vintage, expected listed ≤ 2021-10-13 so
  the common window equals the full region and Amendment 1's coverage asymmetry cannot recur), plus 10
  pre-declared reserve names so any substitution is not result-informed. **Unburntness proven** against
  the burnt 49, the 49 cached bases (113 files), all 29 bases in prior drafts, the 49-base artifact token
  union, and a whole-tree sweep — with positive controls printed (`ADAUSDT` in 19 files, `OMGUSDT` 6,
  `QTUMUSDT` 1) so the zero is not vacuous. Two of its own bugs are recorded: a `[:-4]` on already-stripped
  regex groups produced a **vacuously clean zero**, and a self-validation gate that reads its own draft
  (`prereg-draft-20261016.md:169-173`) rejects every universe ever drafted here.
- **Design:** no train/outer split (nothing is selected on the data), one read of the whole window, 4 fixed
  sequential folds, one timeframe, one frozen config, **no grid search**. Stratification is a binary
  partition fixed in advance (`boundary` {00,08,16} vs `non-boundary` {04,12,20}) with no re-bucketing
  permitted. Primary metric Δ = trade-weighted **gross** (G0) expectancy difference; gross is primary
  because a net-only difference is exactly the turnover-reducer artifact that burned this programme twice.
- **Cost ladder** G0/S1/S2/**S3**/S3t/**S4**, with S3 unchanged as the go/no-go scenario and a pre-declared
  tighter S3t (2 bp slip) for this less-liquid cohort; criteria require S3 **and** S3t, never relaxed.
  Effect floor fixed now at Δ ≥ +10.0 bp/trade, justified definitionally (a 12 bp round trip).
- **Nine acceptance criteria, all required** (C1 non-vacuity ≥50 pooled / ≥5 in 10 of 12 symbols /
  ≥4.9-year window — failure means **not run**, not fail; C2 direction+magnitude; C3 symbol-clustered
  permutation p<0.05, ≥10,000 permutations, seed recorded; C4 breadth ≥8 of 12 paired; C5 edge relevance
  on gross **and** net under both S3 and S3t; C6 Δ>0 in ≥3 of 4 folds; C7 mechanism specificity — if only
  00:00 is positive the verdict is **mechanism unidentified → FAIL**, written in advance so a daily-close
  story cannot be adopted later; C8 cost-confound guard, funding Δ <1.0 bp; C9 concentration on
  notional-weighted net **dollars**, share <0.40 and HHI <0.20 — the limit that just failed, restated not
  renegotiated). Ceiling if all nine pass: **RESEARCH CANDIDATE** — no paper, no live, no sizing, no
  deployment, no change to `oa_algo20.py`. Any single failure closes the hypothesis and burns all 22 names.
- **Measure-naming rule preserved:** `LOOP_SPEC.md:295-302` records that the unweighted per-trade bp mean
  and notional-weighted dollars **disagree in sign** for the same symbol (SNX +21.13 bp but −812 dollars)
  and that an independent re-read once used the wrong one and reached the wrong verdict.
- **What it needs from a human (`:10-11`, `:113-116`):** formally declare the universe plus three metadata
  facts under the declaration gate. Listing start dates, continuous listing, and current USDT-M perp
  existence for all 12 candidates and 10 reserves are **assumed and unverified** — no network was used by
  instruction — so the draft cannot declare itself, and a broken implementation may not consume a universe.

---

## 6. Security, credentials and containment

### 6.1 One live plaintext secret — act on this

`LIVE` (verified 2026-10-18, value deliberately not copied here):
**`/Users/aryanagarwal/COMMAND_CENTER_ARCHITECTURE.md:218` contains a full `nvapi-…` API key in
plaintext, 70 characters.** Lines 219–220 reference the fallback *env var names* only
(`NVIDIA_API_KEY_FALLBACK`, `…FALLBACK2`), which is the correct form.

This contradicts `PROJECT_MEMORY.md:315-329`, which states "No plaintext secrets found." `RETRACTED`.
I did **not** edit that file — revoking or redacting a live key is yours to authorize.

### 6.2 Claims I checked and could NOT confirm

`RETRACTED` (digest-sourced, disproven by my own scan): the assertion that
`HANDOFF-cloudflare-2026-10-11.md:75-77` still carries live `cfut_` / `mstrl_` / `AKIA` / JWT
fragments in plaintext. A whole-file pattern scan for `cfut_`, `mstrl_`, `AKIA`, `cfat_`, `eyJ…`,
`nvapi-`, `sk-`, `gh[pousr]_` returned **NONE FOUND**. The file does *record revocation work as owed*
(push `d803ddb`, revoke 3 `cfut_` tokens, rotate the current token) without exposing the values.

`RETRACTED` (contradicts a project-memory note): **the main fleet checkout's `.git/config` currently
contains no embedded credential** — re-measured 2026-10-18 18:4x IST: `origin` is
`https://github.com/krisharyanagarwal-dev/openalice-fleet.git` with **no `user:pass@` form** and **0**
`gh[pousr]_` literals in the file. Note the token *was* written there by the rotation script earlier —
the fix for that is live but **uncommitted**, in worktree `/Users/aryanagarwal/fleet-worktrees/rotate-no-embed`
at `b89f89a` (branch `qoder/rotate-no-embed`). So "clean" describes the main checkout right now, not the
repo's whole history, and another rotation could re-embed it. Re-verify with §12.1 before citing either way.

Clean of credential-shaped strings (`UNVERIFIED` beyond shape): all `openalice/fleet-state/*`,
`openalice-team-data/MANIFEST.txt`, `openalice-backups/unpublished-snapshot-*/*`,
`agent-handoffs/TEAM_RUN_TEST.md`, `agent-handoffs/openalice-team-run-next.txt` (states
`CREDENTIAL_STATUS=UNCONFIRMED`), `AUDIT.md`, `HOSTILE_TEST_SUMMARY.md`, `MCP_SETUP_GUIDE.md`,
`MCP_STATUS_REPORT.md`, `errors.md`, `llm_provider_degradation.md`, `mm_multi_leg_strategies_guide.md`.
`openalice-backups/office-phase1-*/MANIFEST.txt:2` records a remote-url already as
`REDACTED-ON-PURPOSE (embeds credential)` — keep that redaction.

In the fleet corpus: **no credential literal at all.** Patterns checked `nvapi-`, `sk-`,
`ghp_/ghs_/gho_`, `github_pat_`, `xox*`, `AKIA`, `Bearer <literal>`, `BEGIN *PRIVATE KEY`,
`https://<user>:<pass>@`, and `token|key|secret|password=` assignments; the 22 long-token hits were git
SHAs and identifiers. Four near-misses worth naming: a `Bearer $T` **shell variable** in
`docs/…/github_account_flag_evidence.md:46,49,55`; a 20-char AlphaInsider `strategy_id` (an account
identifier, not a key) in `docs/incidents/2026-09-27-alphainsider-cash-settlement.md`; the literal
placeholder word `test-key` in `VERIFICATION_NOTES.md:43`; and prose describing a PAT embedded in the
**mini's** remote URL (`AGENTS.md:117`, `mini_outage_2026-10-17.md:50`) — the token is on the mini, not
in these files. Real secrets live outside the docs: `.env.llm` (exists, gitignored) and a keychain item
read by `bin/run-pubserver.sh:3`.

### 6.3 Access-control findings worth keeping

- `:3002` pubserver is gated by **one shared secret** `OPENALICE_PUBSERVER_PASSWORD`, and **any
  username is accepted** (`AUTONOMOUS_WORK_STATE.md:12-14`). Loopback-only;
  `192.168.29.202:3002` refused (`:17`).
- `AUTONOMOUS_WORK_STATE.md:643` — **"the HUD has NO in-app authentication"**: its whole API answers
  200 unauthenticated from the tailnet, and `:638`/`:662` name **nine mutating routes** left
  unprotected (polymarket start/stop/trades/clear, LLM circuit-breaker + cost resets,
  `sessions/:id/reattach`).
- `hive/` is unversioned (`.gitignore:56`), so fleet orchestration history is not recoverable.
  `AGENTS.md:129` claims hive is excluded from git — only 2 files are tracked and the 3
  `hive/terminal-tasks/*.md` are **untracked**, i.e. invisible to any git-based merge (`RETRACTED`).
- `openalice/fleet-state/public_url.txt:1` holds a `*.trycloudflare.com` tunnel hostname (likely dead).
  Referenced by path, not pasted here.
- `AUTONOMOUS_MASTER_PROMPT.md:9-15` risk charter: `MAX_POSITION 10 BTC`, `ORDER $25k`,
  `LOSS $500`, `DAILY $2,000`, 3 positions, `$100` risk; `AUTONOMOUS_STATE.md:16` equity $100,000,
  `:21` daily loss $0/$2,000. That approval-gated loop was **never executed** — the log holds six
  checkpoints, every one `Iteration: 0` (`LIVE` by file read).

### 6.5 Redaction proof — scan actually ran, and what it returned

After writing, this document was re-scanned against the full credential pattern set: `nvapi-`, `sk-`,
`ghp_/ghs_/gho_`, `github_pat_`, `AKIA`, `cfut_`, `cfat_`, `mstrl_`, `eyJ…` (JWT),
`https://<user>:<pass>@`, `Bearer <literal>`, `BEGIN *PRIVATE KEY`.

Result: **zero real secrets.** The scan returns **5 shape hits, all prose false positives**, itemised so
the check is auditable rather than merely reassuring — `task-specific` matched the `sk-` pattern twice
(lines 299, 336) and the string `https://<user>:<pass>@` matched the URL-credential pattern three times
(lines 264, 296, 300); that string is the **name** of a pattern §6.2 and §12.1 scan for, never a URL that
appears in this document. No `nvapi-`-shaped token, no `gh[pousr]_`, no `AKIA`, no JWT, no `Bearer`
literal and no private-key block is present anywhere in the file. The live `nvapi-` key from §6.1 is
referenced by file:line and length only. Re-run counts with the command in §12.1; a clean run against
this exact file reports `TOTAL shape hits: 5`, `real secrets: 0`.

---

## 7. Operations, automation and known-broken jobs

`LIVE` (measured this session + by a delegated read-only fleet audit at ~18:00 IST):

- `com.aryan.audit` **is firing hourly** — `AUDIT_DONE stamp=20261018T113503Z` (17:05 IST),
  `latest.md` symlink same time. A prior-exit code of 2 is a **severity** value, not a failure.
- `com.user.opencode-fleet-monitor` heartbeat fresh (`2026-10-18 18:00:02 scan=0`); watchdog pids
  alive; snapshot reads `total_windows: 1, working_sessions: 0`.
- **Broken, needs attention:** the archive push fails —
  `fatal: repository …/github-opencode-archives.git not found`, then
  `ALARM: snapshot captured but NOT archived (rc=1)`. Snapshots are being taken and lost.
- **Broken, needs attention:** `:20241` cloudflared is offline with **no local process and no
  listener** (`LIVE`, 0 listeners) — so whatever was published through it is unreachable. The mini
  tunnel is *not* the problem (`:4748` listening, HTTP 200 from `As-Mac-mini`).
- HUD suite: 3 failures in `office-hud`'s service-lifecycle suite are **pre-existing at HEAD**; the
  `/api/services` POST routes are 405-dead behind the read-only gate.
- `mini_outage_2026-10-17.md` records the deployment host offline at the network layer that day — so
  every "verified on mini" figure inside the audit docs is **unverifiable today** (`UNVERIFIED`).
- Divergence between two OpenAlice clones on this laptop, and 19 worktrees on
  `feat/hud-service-lifecycle`, are documented in `docs/git-divergence-audit.md` (7,123 B) and the
  team-run preflight (`agent-handoffs/openalice-team-run-next.txt:29-33`).

---

## 8. Qoder Agent Team — status as merged from today's work

The fleet's own handoff defines this pending task; it is part of "all openalice", so it is in scope.

Requirements verbatim from `agent-handoffs/openalice-team-run-next.txt:10-18`: human selects the named
saved team in Qoder Desktop; the leader delegates to actual configured members; ≥1 real member response
with a distinct session ID and task-specific output; verify workspace access per member; capture initial
git state and prove it unchanged; **if delegation cannot be proven, report BLOCKED**; no trading, orders,
commits, pushes, merges, deployments or service changes; no credential exposure or remote git while
containment is unconfirmed. `TEAM_RUN_TEST.md:46`: if the saved team is absent, "stop and report the
exact blocker. Do not fabricate member outputs or session IDs."

Measured today: `LIVE` **no team has ever initialized** (no team/squad dir or file under `~/.qoder` or
`~/Library/Application Support`); `QODER_AGENT_TEAMS` unset and `~/.qoder/.env` absent; `mcp_list
keyword=team|squad` → 0 tools; `qodercli agents list` → **5 active agents** (2 user:
`backtest-verifier`, `fleet-state-auditor`; 3 built-in) so a leader+member roster is now **formable**,
which was false yesterday. The Agent Team runtime is **fully implemented** in
`qodercli-1.1.66` (`isAgentTeamsEnabled`, roster locks, `teammate_spawned`, `team-lead`, the
`teams/<name>/{config.json,inboxes,members}` store) but teammates spawn with
`tmux_session_name/window/pane` hardcoded `"in-process"`, so an in-app Desktop session cannot observe a
CLI TUI team. Dispatching named `Agent`-tool subagents produces genuine parallel, member-unique work —
and is **not** a team: the resulting session transcript marks 34 sidechains with `teamName` 0 occurrences.
Remaining unblock is human-only: save the team and pick it in the executor picker, or set the flag and
run the CLI TUI.

---

## 9. Contradiction register

Each row: the disagreement, both sources, and what I measured where measurable.

| # | Subject | Claim A | Claim B | Resolution |
|---|---|---|---|---|
| C1 | Same frozen config, confirmatory universe | `cycle_005` gross −6.12 / net −19.32, 982 trades | `cycle_014` gross −11.0 / net −24.19, 976 trades | **unresolved; B is later and worse.** Report must be corrected or cited with both |
| C2 | 5m `rsi_meanrev_ls` leg | `services/README.md:64-68` +$38,947, 68.2% win | `FINAL_REPORT.md:148-150` loses ~half its equity per quarter | **A is methodology-free** ⇒ A does not survive |
| C3 | Port 4747 | `office-hud/electron/COORDINATION.md:80`, `LAUNCH-CHECKLIST.md:43,57` — it *is* the SSH forward to the mini | `AGENTS.md:56` — local HUD, explicitly "not a tunnel" | `LIVE` **B wins** (local node; `:4748` is the forward) |
| C4 | HUD launchd label | `com.aryan.office-hud` | `com.aryan.office-hud-server` | `LIVE` **B wins** (that is what is loaded) |
| C5 | trading-bot label + port | `com.user.tradingbot` +4 sub-labels, `:8765` | `com.aryan.trading-bot`, `:8000` metrics | `LIVE` **both wrong** — neither label loaded, no plist in `launchd/`, **0 listeners on 8765 or 20241** |
| C6 | Harness supervisor label | `com.aryan.openalice-manager` | `services/README.md:50-54` five `com.openalice.*` labels | `LIVE` **neither installed**; all `com.openalice.*` labels exist in no plist ⇒ `RETRACTED` |
| C7 | Git origin account, inside one file | `AGENTS.md:14` `goodwearrinfo-aryan/openalice-fleet.git` | `AGENTS.md:117,127` `krisharyanagarwal-dev/…` | `LIVE` both accounts appear in the same file; `gh auth switch … --user krisharyanagarwal-dev` is the documented selector. Treat either as unverified until re-checked |
| C8 | Repo root | `/Users/a/trading/openalice-fleet` (~24 docs, canonical per `AGENTS.md`) | `/Users/aryanagarwal/openalice-fleet` | `LIVE` **B on this host**; `/Users/a` does not exist here — A describes the mini |
| C9 | Python interpreter | `AGENTS.md:28-29` — `/usr/bin/python3` has pytest; brew 3.14 has none | `bin/run-tests.sh:9-12` + `cpython-314` pycache | `LIVE` **inverted**: `/usr/bin/python3` has **no** pytest, brew python is **absent**, Framework **3.14 is the real one** |
| C10 | LocalAI port | `ARCHITECTURE.md:41` 8081 | `AGENTS.md:103` 8090 | unresolved; 8081 is ws_server per `services/README.md:8`; LocalAI not installed |
| C11 | Mini address | `192.168.29.202` (`AGENTS.md:11`, `PROJECT_MEMORY:161,339`) | Tailscale `100.125.24.105` (`mini_outage…:12`) ; `192.168.29.254` (`openalice-ui` docs) | unresolved — LAN vs tunnel vs a third value |
| C12 | nested repos | `office/README.md:20`, `COORDINATION.md:11-12` call `office-hud/` and `hive/` nested repos | `TRADING_HANDOFF.md:185` "hive has no git remote" | `LIVE` both misleading: hive resolves to the parent toplevel and inherits origin; **298 office-hud files are tracked in the parent** |
| C13 | loop cadence | `LOOP_SPEC.md:86` every 15 min; `:88` originally every 6 h | `LOOP_LEDGER_NOTES.txt:1` cron `0 9 * * *` → changed `2026-10-15` to `* * * * *` (every minute) | three incompatible cadences in one project |
| C14 | Track A accrual | `LOOP_SPEC.md:238` cannot accrue until 2026-10-19 | `FINAL_REPORT.md:240` "0 prospective trades, correctly" + `LOOP_LEDGER.json` cycles 8–32 **all aborted on drift** | the 10-19 reset passed and **no document updated the state** |
| C15 | UI ports | `openalice-ui/README.md:61` API `127.0.0.1:47331` | `MCP_STATUS_REPORT.md:30` 47332; 8765 as "viewer" vs trading-bot | unresolved |
| C16 | "ready for live trading" | `SYSTEM_READY.md`, `FINAL_VERIFICATION.md` ("✅ VERIFIED") | `DEMO.md:26` "do not connect to order submission", `SAFETY_VERIFICATION.md:5` "INCOMPLETE", `TRADING_HANDOFF.md:65` | **B wins** — paper-only is the enforced contract |

---

## 10. Do-not-trust register (quick list)

1. `/Users/a/...` paths as this host's layout — that is the mini. `LIVE`.
2. `AGENTS.md` interpreter table and the five `com.openalice.*` launchd labels. `LIVE` false.
3. `README.md`'s "D2C Analytics for Shopify fashion brands" framing. Not this project.
4. `LEGS_PNL_SUMMARY.md` log path and its unqualified live win-rate table. `RETRACTED`.
5. "Phase 2 done" vs "Weeks 5–8 pending" — same date, mutually exclusive
   (`FINAL_SUMMARY.md` vs `TRANSFORMATION_STATUS.md`).
6. Unexpanded heredoc artifacts: `SETUP_CONFIRM.md:6` and `OFFICE_SETUP_SUMMARY.md:39` carry literal
   `$(date)`, `SYSTEM_READY.md:146` carries a literal `EOF` — these were never rendered.
7. `PROJECT_MEMORY.md:315-329` "no plaintext secrets" — falsified by §6.1.
8. `SYSTEM_READY.md`'s `fleet-state/book.json` repo path — the file is at `~/openalice/fleet-state/`.
9. Any "profitable" number quoted without its §5 rejection label.

---

## 11. Pending work, as written in the sources

Attributed; none of it done by this merge.

**Human decisions required (`AUTONOMOUS_WORK_STATE.md`)** — trading-bot on mini vs `origin/main` have
**no merge base** (`:78-89`); 6 h vs 24 h primary horizon policy (`:88`); durable resolution for the
`index.js` gate, options (a)/(b)/(c) (`:445-448`); wire `floor_router.py` into the assignment path
(`:723-725`); identify which writer republishes the frozen `hive/processes.json` (`:860`); floor
functional map go/no-go (`:535-540`); prove each launchd job recovers when killed (`:175`).
Its state is itself frozen at `2026-09-28T11:05:14` (`:855`).

**Cloudflare handoff (`HANDOFF-cloudflare-2026-10-11.md:72-85`)** — push `d803ddb`; revoke 3 still-live
`cfut_` tokens; rotate the current token; 43 non-chat CF models catalogued but never called; fix stale
`check_openrouter_quota`; **do not hand-port to diverged local trees**.

**Provider degradation (`llm_provider_degradation.md:75-84`)** — add jittered backoff; treat
uncredentialed OpenRouter as absent; restoring the OpenRouter key is operator-only. Measured 2026-09-30:
58 agents / 46 failing / 756 failures / 311 successes = **29%**; `openrouter 401×611`,
`localai 404×611`, `nvidia 429×607`, `groq 429×605`, denominator 1,067.

**MCP (`MCP_STATUS_REPORT.md:41`)** — unresolved: the OpenAlice runtime shuts down after ~60 s because
"Alice" never becomes ready.

**Project memory (`PROJECT_MEMORY.md:247-253`)** — 5 prioritised actions, physical Mac mini access first.

**Research (`HOSTILE_TEST_SUMMARY.md:73-77`)** — 4 follow-ups; note this file is **not** a fleet doc
(its paths are `~/experiments/profitability_lab/`) and its √τ ATR-scaling hypothesis was **falsified**.

**Declare-or-kill (§5.3)** — a human must formally declare the funding-clock universe (12 candidates + 10
reserves) and its three metadata gate facts — listing start ≤ 2021-10-13, continuous listing, USDT-M perp
still exists — before any data is fetched. Until then the draft is **not runnable**, and eligibility is
assumed, not proven. Also owed: `cycle_014` (worse than the cited `cycle_005`) is not reflected in
`FINAL_REPORT.md` (§9 C1).

**Team verification** — §8; blocked on a human executor-picker action.

**Durability risk** — the entire edge-probe research cluster is **uncommitted** on a machine where the
worktree pointer is broken (§3). If `~/oa-strat` is lost, §5.1's artifacts are unrecoverable.

---

## 12. Provenance and coverage

Per-dir counts measured by `find <dir> -type f \( -name '*.md' -o -name '*.txt' \)` excluding
`node_modules/`, `.git/` and `.pytest_cache/` (that last exclusion is why these counts are 76 and 47
rather than the 78 and 49 a raw scan returns):

| Directory | Docs | Bytes | Disposition |
|---|---|---|---|
| `openalice-fleet` | 76 | 483,579 | primary source; 23 root docs + 53 nested |
| `oa-strat` | 48 | 324,919 | **20 root docs are byte-identical duplicates** of the fleet copies (`cmp`-verified, all mtime 2026-09-25) and **1 differs** — `AGENTS.md` (fleet 20,117 B, Oct 17 vs oa-strat 5,989 B, Sep 25). Cite the **fleet** path for all of them. **Only `research/edge-probe-*` is unique** and exists nowhere else. Count rose from 47 / 296,096 during this merge — see the live-corpus note at the top |
| `openalice` | 4 | 3,086 | fleet-state snapshots + master prompt + tunnel url |
| `openalice-ui` | 1 | 9,638 | laptop-as-client architecture |
| `openalice-backups` | 3 | 2,750 | two manifests + an unpublished snapshot (baseA `6e641af` deployed, baseB `5a5aafd` **provably stale**, remote main `c205bed`) |
| `agent-handoffs` | 2 | 5,006 | team smoke test + preflight |
| `openalice-team-data` | 1 | 663 | parquet MD5 manifest (12,480 rows each; warns the sibling set is 1,000 bars — "do not substitute") |
| `openalice-fleet-archive-20260925` | 0 | 0 | **no docs** (contains no `.md`/`.txt`) — nothing to merge |
| **subdirectory subtotal** | **135** | **829,641** | |
| home level `/Users/aryanagarwal/*.md` | 11 | 134,158 | 5 in scope (84,094 B), 6 excluded — see filter below |
| **grand total scanned** | **146** | **963,799** | |
| **in scope / merged** | **140** | **913,735** | |

**Excluded from the content merge as not OpenAlice** — `AUDIT.md`, `MCP_SETUP_GUIDE.md`, `errors.md`,
`mm_multi_leg_strategies_guide.md`, `HOSTILE_TEST_SUMMARY.md` (0 OpenAlice mentions each) and
`COMMAND_CENTER_ARCHITECTURE.md` (2 passing mentions — it is a plan for *other* projects,
`deepseek-harness` and `wifi_security_bot`). `llm_provider_degradation.md` never says "OpenAlice" but is
**included** — its content is entirely fleet (`hive/lib/llm/*`, `free_harness_server.py`, port 8080).

Two of the excluded files are still **cited as pointers, not merged as content**: `COMMAND_CENTER_ARCHITECTURE.md`
because it holds the live key reported in §6.1, and `HOSTILE_TEST_SUMMARY.md` because its 4 research
follow-ups (§11) are trading-adjacent work even though its paths are `~/experiments/profitability_lab/`.

**Excluded duplicates:** `Backups/disk-cleanup-20261003/openalice-fleet/AUTONOMOUS_WORK_STATE.md`
(9,831 B, Sep 28) differs from the home copy; `.openalice/AUTONOMOUS_STATE.md` (Sep 4, 12 h-session
format) is a *different older* file, not a copy, of `openalice/fleet-state/AUTONOMOUS_STATE.md`
(Sep 5); two identical 302 B `.pytest_cache/README.md` in the fleet tree; the 20 byte-identical
oa-strat root docs.

**Thematic overlap only, no text duplication:** the fleet root docs contain **zero** mentions of
cloudflare, `OPENALICE_PUBSERVER_PASSWORD`, `isLocalRequest`, `processTruth`, or the HUD truth audit —
those live only in the home-level docs. Three docs tell the same pubserver/HUD/:3002 security story
(`AUTONOMOUS_WORK_STATE.md:12-27`, `openalice-ui/README.md:20-53`,
`openalice-backups/office-phase1-*/MANIFEST.txt`), and that gate saga is retold **inside one file four
inconsistently-numbered times** ("stripped THREE times" `:360-370` → "reopened 6 times" `:484` → "7th
time" `:597` → "8th recurrence" `:658`). The `processTruth` finding is stated twice, near-verbatim, as
"FOUND, not fixed" (`:769-796`) and then "fixed, b936c49" (`:815-852`) — merged here as one item.

**Scale warning, kept honest:** 146 documents (913,735 in-scope bytes ≈ **228k tokens**) were
*inventoried and digested*, not transcribed. A verbatim merge would be unreadable and would silently
promote contradictory numbers into one voice — see the 16 contradictions in §9. This document instead
preserves every **quantitative claim with its file:line and its verdict**, names every contradiction and
retraction, and lists the duplicate and out-of-scope material so nothing is lost by omission. Where I
could test a claim against disk, I did and marked it `LIVE`; where I could not, it says `UNVERIFIED`.
The two digests that fed §5 and §11 were themselves spot-checked, and **two of their claims were
disproven** before publication: the asserted live `cfut_`/`mstrl_`/`AKIA` fragments in
`HANDOFF-cloudflare-2026-10-11.md` (whole-file scan: none present) and the embedded-credential state of
`openalice-fleet/.git/config` (clean today). Both corrections are recorded in §6.2 rather than repeated.

### 12.1 Reproduce this merge's counts and its redaction scan

```bash
# coverage counts — prints docs AND bytes per dir (a bare `wc -c + | tail -1` prints bytes only,
# and prints a filename instead of a total when a dir holds exactly one file)
for d in openalice openalice-fleet openalice-ui oa-strat openalice-team-data \
         openalice-backups openalice-fleet-archive-20260925 agent-handoffs; do
  n=$(find "/Users/aryanagarwal/$d" -type f \( -name '*.md' -o -name '*.txt' \) \
        -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.pytest_cache/*' | wc -l | tr -d ' ')
  b=$(find "/Users/aryanagarwal/$d" -type f \( -name '*.md' -o -name '*.txt' \) \
        -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.pytest_cache/*' \
        -exec wc -c {} + 2>/dev/null | tail -1 | awk '{print $1}')
  echo "$d docs=$n bytes=${b:-0}"
done
# duplicate check (expect 20 identical, 1 differing: AGENTS.md)
same=0; dif=0
for f in /Users/aryanagarwal/oa-strat/*.md; do
  g="/Users/aryanagarwal/openalice-fleet/$(basename "$f")"
  [ -f "$g" ] && { cmp -s "$f" "$g" && same=$((same+1)) || dif=$((dif+1)); }
done
echo "identical=$same differs=$dif"
```

Re-check §6.2's credential claim (prints **shapes and counts only**, never values):

```bash
cd /Users/aryanagarwal/openalice-fleet
git remote -v | sed -E 's#(https://)([^/@ ]*)(@)#\1MASKED_USERPASS@\3#g'
python3 -c "
import re
s=open('.git/config',encoding='utf-8',errors='replace').read()
u=re.findall(r'url\s*=\s*(\S+)',s)
print('urls with user:pass form:', sum(bool(re.search(r'https://[^/@\s]+:[^/@\s]*@',x)) for x in u))
print('gh[pousr]_ literals:', len(re.findall(r'gh[pousr]_[A-Za-z0-9]{8,}', s)))"
```

The redaction scan (§6.5) is a Python pass over this file testing
`nvapi-[A-Za-z0-9_-]{6,}`, `sk-[A-Za-z0-9]{8,}`, `gh[pousr]_[A-Za-z0-9]{8,}`,
`github_pat_[A-Za-z0-9]{8,}`, `AKIA[0-9A-Z]{6,}`, `cfut_`, `cfat_`, `mstrl_`, `eyJ[A-Za-z0-9_-]{10,}`,
`https://[^/\s@]+:[^/\s@]+@`, `Bearer\s+[A-Za-z0-9_-]{16,}` and `BEGIN [A-Z ]*PRIVATE KEY`. It prints
match **lengths only**, never values, so it is safe to run in a shared terminal or paste into a report.
