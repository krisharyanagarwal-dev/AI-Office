"""Monotonic fencing tokens — the mechanism that makes a stale lease holder inert.

One global sequence (`fencing_token_seq`, created by `0003_fencing.sql`) mints every token,
so a value is never handed to two tasks and never handed out twice. `bump_token` is the only
way to get one: it writes the new value onto `tasks.fencing_token` and returns it, and it
returns `None` when the task id matches no row. `task_transition()` refuses any call whose
presented token is not the stored one, so a holder that was granted an earlier token can
still reach the API but can no longer write through it.

Measured, not assumed: a zero-row `UPDATE` does NOT evaluate its SET expressions, so a bump
against a missing task mints nothing and burns no sequence value.
"""

async def bump_token(conn, task_id: int) -> int | None:
    return await conn.fetchval(
        "update tasks set fencing_token = next_fencing_token(), updated_at = now() "
        "where id = $1 returning fencing_token", task_id)
