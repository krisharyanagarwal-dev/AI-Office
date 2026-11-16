"""`task_transition()` is the only permitted writer of `tasks.state`.

Ruling T2-H: the `evidence` argument below is the *transition justification*, which
Postgres redacts into `audit_events.redacted_payload`. Durable per-task evidence lives in
the separate `task_evidence` table and is written by the adapter/API layer, not here —
this wrapper must not grow an INSERT into that table, and `tasks` must not grow an
evidence column.
"""

import json
from dataclasses import dataclass

@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    reason: str
    new_state: str | None

async def task_transition(conn, task_id: int, to_state: str, fencing_token: int,
                          evidence: dict | None, actor: str) -> TransitionResult:
    row = await conn.fetchrow(
        "select * from task_transition($1,$2,$3,$4::jsonb,$5)",
        task_id, to_state, fencing_token,
        None if evidence is None else json.dumps(evidence), actor,
    )
    return TransitionResult(ok=row["ok"], reason=row["reason"], new_state=row["new_state"])
