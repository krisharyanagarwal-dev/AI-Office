# Contract: the Qoder in-app session list

Status: **fixture-only.** No production payload is stored in this repository, and
none of the examples below is a captured sample.

Provenance of every claim on this page: four calls to the in-session MCP tool
`mcp__builtin__list_chat_sessions` made from the Qoder chat session identified by
the directory prefix `3a6e7682` on 2026-10-16/17. The parameters used are
listed with each observation. Nothing here was inferred from documentation, and
nothing here was verified by a fifth method. The full conversation id is
deliberately not recorded in this repository: it is a real identifier from the
population this contract describes, and a fixture-only repo has no need of it.

---

## 1. Observed facts

### 1.1 Envelope

| Key | Observed type | Observation |
|---|---|---|
| `kind` | string | Always `"qoder.chatSessions.listed"` in all four responses |
| `sessions` | list of objects | 42, 1, 2 and 1 rows respectively across the four calls |
| `nextCursor` | string or `null` | `"1"`, `"2"`, `null`, `"1"` |

No other top-level key was ever seen.

### 1.2 Per-session fields

Eight keys, present in every row of every response observed:

| Field | Type | Notes on the observation |
|---|---|---|
| `sessionId` | string | Lowercase hex UUID, 36 characters |
| `title` | string | Human label; free-form, not unique, some rows shared a title exactly |
| `cwd` | string | Absolute path; several distinct sessions shared one `cwd` |
| `updatedAt` | integer, **milliseconds** | 13 digits; see 1.4 |
| `runtimeState` | string | Four distinct values seen; see 1.3 |
| `pendingInteractionCount` | integer | `0` in every row observed except one, which was `1` |
| `unread` | boolean | Both values seen |
| `archived` | boolean | `false` in the default filter, `true` in the `archived: true` call |

### 1.3 Runtime states observed

`running`, `ready`, `waiting-user`, `cold`.

That is a list of what was seen, not a vocabulary. Note the hyphen in
`waiting-user`; `waiting_user` has never appeared and would not be recognised.

### 1.4 Timestamp unit

`updatedAt` is epoch **milliseconds**. Forced by the numbers, not chosen:
`1792175993047` decoded is `2026-10-16T18:39:53.047Z`, which was 1.5 minutes
before the clock of the call that returned it. The same value read as seconds is
outside the representable year range.

Local timezone on this host is `Asia/Kolkata` (UTC+05:30); that same stamp is
`2026-10-17T00:09:53+05:30` there.

### 1.5 Cursor arithmetic

| Call | `limit` | Rows returned | `nextCursor` |
|---|---|---|---|
| A | 50 | 42 | `null` |
| B | 1 | 1 | `"1"` |
| C | 2 | 2 | `"2"` |
| D | 1, `archived: true` | 1 | `"1"` |

`nextCursor` equals **the number of rows consumed so far** — an item offset, not
a page index. The tool's own input schema constrains it to `^\d+$`, max 10
characters, and tells the caller to reuse the value with the same `archived`
filter.

### 1.6 Archived filter

`archived` defaults to `false`. Passing `archived: true` returns a separate
population; one such row was observed, `runtimeState: "cold"`, `archived: true`.

### 1.7 Producer boundary

`list_chat_sessions` is reachable only from inside a Qoder agent turn. There is
no `mcp_call` executable on this machine's PATH and no importable
`mcp_builtin_list_sessions` module for any interpreter. The Qoder app does listen
on a loopback MCP router whose key authenticates, but it returned `404 Not Found`
for every path tried (`/`, `/health`, `/mcp`, `/sse`; GET and POST; JSON-RPC
`initialize` and `tools/list`). Its route table was not brute-forced.

Consequence: **no script of any kind can fetch this data by itself.** Any
"cron job runs a python feed" design is a fabrication. See §4.

---

## 2. Proposed output-schema fields

Everything below is invented by this package. None of it is guaranteed by
anything upstream, and the serialized snapshot labels it as such under
`provenance`.

| Field | Layer | Status |
|---|---|---|
| `schemaVersion` | snapshot | proposed; integer, currently `1` |
| `observedAtMs` | snapshot | proposed; unit stated in the name to avoid a seconds/milliseconds mix-up |
| `producer` | snapshot | proposed; free-form label |
| `source.{tool,envelopeKind,paginationVerified}` | snapshot | proposed; self-description |
| `provenance.*` | snapshot | proposed; honesty metadata |
| `evidence.*` | snapshot | proposed; read-window, see §2.1 |
| `claims.*` | snapshot | proposed; computed from `evidence`, never authored by hand |
| `qoderRuntimeState` | row | **proposed rename** of `runtimeState` — see §4.2 |
| `statusLabel` | row | proposed derived label, provisional mapping |
| `unexpectedFields` | row | proposed; preserves keys upstream adds |

### 2.1 Evidence keys

`count`, `scanned`, `pagesFetched`, `cursorOffsets`, `terminalCursorSeen`,
`duplicatesSeen`, `identicalDuplicates`, `cutOff`, `truncated`,
`inconsistencies`, `unexpectedRowFields`, `suspiciousTimestampCount`, `checkedAt`,
`ok`, `status`, `error`.

`count`, `scanned`, `truncated`, `checkedAt`, `ok`, `status`, `error` and the
status names `empty_in_window`, `window_truncated`, `unreadable`, `no_answer`
are **reused deliberately** from an existing discipline in
`office-hud/web/src/deskTruth.ts`, which was written to stop a floor claiming
"0 commands" from a log it had only partly read. `inconsistent`, the
cursor-walk keys and the entire completeness axis are new here, because that
file describes a single file read rather than a paginated walk.

### 2.2 Provisional status mapping

| `runtimeState` | `statusLabel` |
|---|---|
| `running` | `working` |
| `ready` | `available` |
| `waiting-user` | `pending_approval` |
| `cold` | `off_shift` |
| anything else | `UNKNOWN` |

The mapping is unapproved. The `UNKNOWN` fallback is not a preference: the
superseded design specified "invalid `runtimeState` → default to `cold`", which
renders an unrecognised state as a worker who has gone home.

---

## 3. Unverified assumptions

1. **That four states are the whole vocabulary.** Two further values could exist
   that no call has surfaced.
2. **That `null` means "no more rows" rather than "not paginating".** It is the
   only terminal signal available and it is assumed, not proven.
3. **That offsets stay valid as the roster reorders.** Results are ordered by
   `updatedAt` descending and §4.1 shows that order moving. Assumed usable, but
   the walk is only safe because drift is *detected*, not because it is absent.
4. **That `total` never exceeds the 50-row page.** The one call with more than
   two pages was never exercised — see §4.3.
5. **That extra keys upstream will be additive and benign.** They are preserved
   and reported, not trusted.
6. **That `title` is unique.** It is not: exact duplicates were observed. `sessionId`
   is the only identity used.
7. **That `pendingInteractionCount` counts what its name suggests.** Untested
   against the UI.
8. **`max_pages = 20` and `clock_skew_ms = 0` are arbitrary.** Both are guards,
   neither is calibrated.
9. **Whether archived sessions belong in any eventual floor is undecided.**

---

## 4. Known consistency limitations

### 4.1 The roster moves while it is being read — observed, not theorised

Between call A and call C, a session that had not been in the 42 appeared at the
head of the list, and this session's own `updatedAt` advanced by minutes. The
producer is a member of what it measures: results sort by `updatedAt`
descending, and the agent reading them is the most recently active session in
the set.

Effects: a row can move to a later offset (it appears twice) or an earlier one
(it is skipped). A **duplicate is detectable** — arithmetic, cursor repetition
and a repeated `sessionId` all catch it. **A skip is not detectable at all**,
because the envelope declares no total count.

That asymmetry is the reason `can_claim_absence` and `can_claim_complete` are
two separate functions. Deduplication makes a roster *clean*; it does not make
it *whole*.

### 4.2 `runtimeState` is a name collision across two populations

The office-hud server already publishes `runtimeState` for opencode fleet agents,
with values `busy`, `idle`, `offline`, `breaker`, `error`, `UNKNOWN`
(`office-hud/server/lib/dots/systems/floorSystem.js`, `taskSystem.js`,
`agentSystem.js`). A Qoder feed that kept the original key name would let two
unrelated vocabularies color the same desk. Hence `qoderRuntimeState`, and
`validate_snapshot` rejects any row that carries the bare `runtimeState` key.

The rename is a proposal. The collision is not.

### 4.3 Pagination has never been exercised beyond two rows

Calls B, C and D each returned exactly one page, and call A returned everything
in one page. **No multi-page walk against a real roster has ever run.** The
offset arithmetic in this package is derived from the relation between `limit`,
row count and `nextCursor` in those single-page responses. The reducer is tested
against synthetic multi-page walks, including the drift in §4.1, but those prove
the reducer's rules, not the upstream behaviour.

### 4.4 No error contract exists yet

Every observation was a success. No failing response has been seen, so this
package models **no** error envelope: input that does not match the observed
success shape raises `EnvelopeMalformed` with a reason. That is our rejection,
not the API's. When a real failure is eventually captured, the error shape must
be added as an observation, never guessed.

### 4.5 `~/.qoder/tasks/` is not a schedule store

248 directories named by session id, each holding numbered `N.json` files — a
per-session task board. `~/.qoder/cron/` does not exist; automations are managed
through the `qoder_cron` tool (9 jobs observed, each with a
`executionScope.kind: "directory"` and a `cwd`). Neither is a source of session
roster data, and this package reads neither.
