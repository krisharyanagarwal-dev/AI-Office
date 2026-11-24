# qoder-session-floor

S1 only: the read contract for Qoder's in-app chat sessions, as pure functions.

This is **not** the office floor. It is the layer underneath it — the part that
decides what a read of the session list is allowed to claim, and what it is not.

## What exists here

| Module | Responsibility |
|---|---|
| `contract.py` | Field names, types and states that were **observed**, kept apart from what was invented |
| `envelope.py` | `parse_envelope` — validate one captured page, or refuse it |
| `pagination.py` | `fold_page` — accumulate a cursor walk as an item offset, detect drift |
| `evidence.py` | `read_status`, `can_claim_absence`, `can_claim_complete`, `read_label` |
| `states.py` | The provisional `runtimeState` → `statusLabel` layer, deliberately separate |
| `snapshot.py` | `build_snapshot`, `validate_snapshot`, `serialize_snapshot`, `parse_snapshot` |

```bash
python3 -m pytest            # everything, offline, synthetic fixtures only
```

## Boundaries, and why they are shaped like this

- **Fixture-only.** No real roster is stored, and none may be added without
  separate authorization. The test that would compare a real capture against the
  fixture shape is present and deliberately skipped, so its disappearance would
  be visible.
- **No I/O in the package.** Nothing here can call MCP, the network, a shell, or
  a file — enforced by an AST scan in `tests/test_purity.py`, whose detector is
  proven against injected violations before its clean verdict counts. That
  boundary is not stylistic: the previous design of this system was a Python feed
  writer importing `mcp_builtin_list_sessions` and shelling out to a
  non-existent `mcp_call` binary. Neither exists. A read happens inside an agent
  turn; this package only ever receives what that turn already captured.
- **Absence is a claim, not a default.** `can_claim_absence` is true in exactly
  one status. The evidence vocabulary is reused from `office-hud/web/src/deskTruth.ts`,
  a module written because a partly-read log once reported `count: 0` truthfully
  and "nothing was ever asked" falsely.
- **Completeness is a separate axis.** A cursor walk can detect a repeated row
  and cannot detect a skipped one, because the upstream envelope declares no
  total. So deduplication never upgrades a read to "the whole roster".
- **Nothing is connected to the HUD.** F18 is already "The Desk"; the next free
  floor is F21, and using it is a later decision, not implied by this repository.

Start with [`docs/contract-session-list.md`](docs/contract-session-list.md): it
separates observed fact, proposal, assumption and known limitation, and records
the four calls each claim came from.
