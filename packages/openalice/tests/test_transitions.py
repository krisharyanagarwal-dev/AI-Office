import json

import asyncpg
import pytest

from authority.transitions import task_transition

async def seed(conn, state="CREATED", token=0, slot=None, adapter="qoder", verified=True):
    """Seed a task and, optionally, the slot it is assigned to.

    DEFECT FOUND IN THE BRIEF. As written, `seed` always inserted the slot as
    `('qoder', verified_at=now())` and then two of the tests inserted the SAME slot id
    again in the test body to describe the slot they actually wanted, so both died with
    `duplicate key value violates unique constraint "worker_slots_pkey"` before reaching a
    single assertion. The helper now takes the slot's adapter and verification state as
    parameters — which is what the brief's dead `verified=True` argument was for — so each
    test describes its slot exactly once. The two negative cases stay distinct and both
    still terminate in SLOT_NOT_VERIFIED: a slot that IS verified but whose adapter is
    'mock', and a real adapter that has never been verified. The first is the case that
    dies if Task 11's mock-adapter mutant is applied.

    The two head rows are `on conflict do nothing` so a test may seed two tasks (the
    rejection sweep needs one live task per guard plus one absent id) without colliding on
    the single prompt/role the fixture creates."""
    await conn.execute("insert into prompts(id) values('p1') on conflict (id) do nothing")
    await conn.execute(
        "insert into roles(id,name,profile_version) values('r1','T',1) on conflict (id) do nothing")
    if slot:
        await conn.execute(
            "insert into worker_slots(id,adapter,verified_at) values($1,$2,"
            "case when $3::boolean then now() else null end)",
            slot, adapter, verified)
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective,state,fencing_token,assigned_slot_id) "
        "values('p1','r1','o',$1,$2,$3) returning id", state, token, slot)

async def test_legal_transition_writes_state_audit_and_outbox_atomically(conn):
    tid = await seed(conn)
    res = await task_transition(conn, tid, "PLANNED", 0, None, "tester")
    assert (res.ok, res.reason, res.new_state) == (True, "OK", "PLANNED")
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "PLANNED"
    assert await conn.fetchval("select count(*) from audit_events where target=$1", str(tid)) == 1
    assert await conn.fetchval("select count(*) from outbox_events where task_id=$1", tid) == 1

async def test_illegal_edge_is_rejected_and_state_untouched(conn):
    tid = await seed(conn)
    res = await task_transition(conn, tid, "COMPLETED", 0, None, "tester")
    assert (res.ok, res.reason) == (False, "ILLEGAL_EDGE")
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval("select count(*) from audit_events") == 1, "rejection not audited"

async def test_unknown_task_is_not_found(conn):
    res = await task_transition(conn, 999999, "PLANNED", 0, None, "tester")
    assert (res.ok, res.reason) == (False, "NOT_FOUND")

async def test_requires_evidence_edge(conn):
    tid = await seed(conn, state="RUNNING")
    assert (await task_transition(conn, tid, "VERIFYING", 0, None, "t")).reason \
        == "EVIDENCE_REQUIRED"
    assert (await task_transition(conn, tid, "VERIFYING", 0, {"tests": "pass"}, "t")).ok is True

async def test_queued_requires_a_verified_non_mock_slot(conn):
    tid = await seed(conn, state="APPROVED", slot="s-mock", adapter="mock")
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert (res.ok, res.reason) == (False, "SLOT_NOT_VERIFIED")

async def test_queued_rejects_an_unverified_real_slot(conn):
    tid = await seed(conn, state="APPROVED", slot="s-raw", verified=False)
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert (res.ok, res.reason) == (False, "SLOT_NOT_VERIFIED")

async def test_queued_accepts_a_verified_real_slot(conn):
    tid = await seed(conn, state="APPROVED", slot="s-ok")
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert res.ok is True


# ---------------------------------------------------------------------------
# Proofs the brief asked for but did not contain. Each one below exists because a
# claim about this function was asserted somewhere and not measured.
# ---------------------------------------------------------------------------

async def test_a_refusal_returns_exactly_one_row_and_writes_nothing(conn):
    """PL/pgSQL's `RETURN QUERY` does not exit the function — only a plain `RETURN` does.

    The brief's body relied on that false assumption five times, and live measurement on
    the brief's own SQL showed what that means: one refused CREATED->COMPLETED emitted TWO
    result rows, set tasks.state to COMPLETED, wrote the ILLEGAL_EDGE reject row *and* an
    OK audit row, and queued a `task.COMPLETED` outbox event. Because the wrapper reads the
    first row, every reason-code assertion in the suite stayed green while the write
    happened anyway — a sole writer that writes on refusal is not a sole writer.

    So the refusal contract is pinned structurally, not by reading the reason code: exactly
    one row, no second OK row, no state change, no event, one audit row."""
    tid = await seed(conn)
    rows = await conn.fetch(
        "select * from task_transition($1,$2,$3,$4::jsonb,$5)", tid, "COMPLETED", 0, None, "tester")

    assert len(rows) == 1, f"{len(rows)} rows from one refusal — execution fell through the guard"
    assert (rows[0]["ok"], rows[0]["reason"]) == (False, "ILLEGAL_EDGE")
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval(
        "select count(*) from audit_events where outcome='OK'") == 0, "refusal wrote an OK audit row"
    assert await conn.fetchval("select count(*) from outbox_events") == 0, "refusal queued an event"

async def test_transition_and_its_rows_rollback_together(conn):
    """§10 claims `task_transition` writes tasks, audit_events and outbox_events *in one
    transaction*. That is only true if it is measured with a forced rollback, and the
    in-transaction reads below are what make the final assertions mean something: without
    them, a transition that wrote nothing at all would also 'roll back' cleanly."""
    tid = await seed(conn)
    try:
        async with conn.transaction():
            assert (await task_transition(conn, tid, "PLANNED", 0, None, "tester")).ok is True
            assert await conn.fetchval("select state from tasks where id=$1", tid) == "PLANNED"
            assert await conn.fetchval("select count(*) from audit_events") == 1
            assert await conn.fetchval("select count(*) from outbox_events") == 1
            raise RuntimeError("simulated crash after the transition wrote its rows")
    except RuntimeError:
        pass

    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval("select count(*) from audit_events") == 0, "orphan audit row"
    assert await conn.fetchval("select count(*) from outbox_events") == 0, "orphan event"

async def test_every_rejection_reason_is_audited(conn):
    """Silence is how the four blocked registries on 2026-10-31 looked healthy.

    All five reason codes are driven through the function on two live tasks plus one absent
    id, and each has to leave exactly one audit row carrying its own code, the token that
    was presented, and no outbox event. NOT_FOUND is included deliberately: the brief
    returned it without an audit row, which left a refused attempt indistinguishable from
    one that was never made."""
    mock_slot_task = await seed(conn, state="APPROVED", slot="s-mock", adapter="mock")
    running = await seed(conn, state="RUNNING", token=3)
    missing = 999999

    cases = [
        (missing, "PLANNED", 0, None, "NOT_FOUND"),
        (running, "VERIFYING", 0, None, "BAD_TOKEN"),
        (running, "COMPLETED", 3, None, "ILLEGAL_EDGE"),
        (running, "VERIFYING", 3, None, "EVIDENCE_REQUIRED"),
        (mock_slot_task, "QUEUED", 0, None, "SLOT_NOT_VERIFIED"),
    ]
    for task_id, to_state, token, evidence, reason in cases:
        res = await task_transition(conn, task_id, to_state, token, evidence, "auditor")
        assert (res.ok, res.reason) == (False, reason)
        assert await conn.fetchval(
            "select count(*) from audit_events where outcome=$1 and target=$2 and actor='auditor'",
            reason, str(task_id)) == 1, f"{reason} rejection was not audited"
        assert await conn.fetchval(
            "select fencing_token from audit_events where outcome=$1", reason) == token, \
            f"{reason} audit row lost the token that failed"

    assert await conn.fetchval("select count(*) from audit_events") == 5
    assert await conn.fetchval("select count(*) from outbox_events") == 0, "a refusal queued an event"
    assert await conn.fetchval("select state from tasks where id=$1", running) == "RUNNING"
    assert await conn.fetchval("select state from tasks where id=$1", mock_slot_task) == "APPROVED"

async def test_the_guard_order_is_token_before_edge(conn):
    """The reasons are only diagnostic if the order is fixed: a request that breaks BOTH the
    token guard and the edge guard must report BAD_TOKEN, because a fenced holder is a
    different incident than an illegal edge, and Task 4's zombie test depends on which code
    a stale writer sees. Swapping the two guards in 0002 turns this red."""
    tid = await seed(conn, token=7)
    res = await task_transition(conn, tid, "COMPLETED", 0, None, "zombie")
    assert (res.ok, res.reason) == (False, "BAD_TOKEN")
    assert await conn.fetchval("select count(*) from audit_events where outcome='BAD_TOKEN'") == 1
    assert await conn.fetchval("select count(*) from audit_events where outcome='ILLEGAL_EDGE'") == 0

async def test_a_null_token_fails_closed_rather_than_passing_the_fence(conn):
    """`v_token <> NULL` is NULL, not true, so the token guard as the brief wrote it falls
    OPEN for a caller that presents no token at all. Measured before the fix: a NULL-token
    CREATED->PLANNED request passed the fence, wrote the state and its OK audit row, and
    only stopped at the NOT NULL constraint on outbox_events.dedupe_key — a
    NotNullViolationError where a reason code was promised.

    Driven straight against the SQL function rather than the wrapper, because the hole is
    in SQL three-valued logic, not in Python: `fencing_token: int` on the wrapper is a hint
    and Task 10's JSON body is not bound by it."""
    tid = await seed(conn)
    rows = await conn.fetch(
        "select * from task_transition($1,$2,$3,$4::jsonb,$5)", tid, "PLANNED", None, None, "zombie")

    assert len(rows) == 1
    assert (rows[0]["ok"], rows[0]["reason"]) == (False, "BAD_TOKEN")
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval("select count(*) from outbox_events") == 0
    assert await conn.fetchval(
        "select count(*) from audit_events where outcome='OK'") == 0, "NULL token wrote an OK audit row"
    assert await conn.fetchval(
        "select count(*) from audit_events where outcome='BAD_TOKEN'") == 1

async def test_evidence_is_the_redacted_justification_not_a_task_evidence_row(conn):
    """Ruling T2-H, pinned rather than promised.

    `p_evidence` is the transition *justification*: it is scrubbed by redact() into
    audit_events.redacted_payload and it must NOT create a row in the durable task_evidence
    table (that is the adapter/API layer's job, and conflating them would put a second
    writer on evidence while this task's whole point is one writer for state). The secret
    here is a synthetic literal with an obvious TESTONLY marker — no real credential exists
    in this file, and spec §12 requires the scrub to happen in SQL, not in Python."""
    tid = await seed(conn)
    secret = "nvapi-TESTONLY0123456789abcdef"
    res = await task_transition(conn, tid, "PLANNED", 0, {"log": secret, "tests": "pass"}, "t")
    assert res.ok is True

    payload = await conn.fetchval(
        "select redacted_payload::text from audit_events where outcome='OK'")
    assert secret not in payload, "the justification reached the audit trail unredacted"
    assert "<redacted>" in payload
    assert "pass" in payload, "redaction destroyed the non-secret part of the justification"

    assert await conn.fetchval("select count(*) from task_evidence") == 0, \
        "task_transition wrote durable evidence — T2-H says that is a different table"
    assert await conn.fetchval(
        "select column_name from information_schema.columns "
        "where table_name='tasks' and column_name='evidence'") is None, \
        "tasks grew an evidence column, which T2-H forbids"

async def test_the_transition_event_names_the_state_and_carries_the_prompt(conn):
    """Task 7 dedupes on `dedupe_key` and Task 10's prompt trace joins audit/outbox back
    through `prompt_id`; neither can work off a row count. The event shape is therefore
    pinned here, at the only place that writes it."""
    tid = await seed(conn, token=4)
    await task_transition(conn, tid, "PLANNED", 4, None, "t")
    row = await conn.fetchrow("select * from outbox_events")
    assert row["event_type"] == "task.PLANNED"
    assert row["prompt_id"] == "p1"
    assert row["task_id"] == tid
    assert row["dedupe_key"] == f"{tid}:PLANNED:4"
    # asyncpg hands jsonb back as raw JSON text, so the payload is decoded, not sliced.
    assert json.loads(row["payload"]) == {"from": "CREATED", "to": "PLANNED", "token": 4}

async def test_completed_at_is_stamped_only_on_a_terminal_state(conn):
    """The `case` in the UPDATE selects four terminal states out of eleven and no test in
    the brief reached it, so it was decoration until now: a mutant that stamped
    completed_at on every transition, or one that stamped it on none, survived."""
    terminal = await seed(conn)
    await task_transition(conn, terminal, "CANCELLED", 0, None, "t")
    assert await conn.fetchval("select completed_at from tasks where id=$1", terminal) is not None
    assert await conn.fetchval("select state from tasks where id=$1", terminal) == "CANCELLED"

    non_terminal = await seed(conn)
    await task_transition(conn, non_terminal, "PLANNED", 0, None, "t")
    assert await conn.fetchval("select completed_at from tasks where id=$1", non_terminal) is None

async def test_the_vocabulary_trigger_does_not_make_the_edge_guard_redundant(conn):
    """TRIPWIRE, NOT AN ENDORSEMENT. §6's sole-writer claim holds only for code that goes
    through task_transition(): review live-proved the 0001 trigger accepts CREATED->COMPLETED
    because COMPLETED is a documented state, and ruling P-6 legitimately grants
    authority_app UPDATE on tasks so the fencing token can be bumped. So the state_edges
    EXISTS guard in 0002 is the only thing refusing that jump, and this test is the proof
    that it cannot be deleted as "already covered by the trigger".

    When Plan 3 moves these writes behind a definer-side function with a pinned
    search_path, the first assertion below stops holding and THIS test must be flipped to
    assert the direct UPDATE is refused — a failure here is the signal that the gap closed,
    never a reason to delete the test."""
    tid = await seed(conn)

    await conn.execute("update tasks set state = 'COMPLETED' where id = $1", tid)
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "COMPLETED", \
        "the direct-UPDATE escape closed — update this tripwire to assert the refusal"

    other = await seed(conn)
    res = await task_transition(conn, other, "COMPLETED", 0, None, "t")
    assert (res.ok, res.reason) == (False, "ILLEGAL_EDGE")
    assert await conn.fetchval("select state from tasks where id=$1", other) == "CREATED"


# ---------------------------------------------------------------------------
# Ruling T3-A — the STORED side of the fencing fence.
#
# The branch above (`p_token is null`) closed the presented side. This is its mirror: the
# value read out of tasks.fencing_token can itself be NULL as far as SQL logic is concerned,
# and `NULL <> anything` is NULL, not true, so the comparison guard skips and the write path
# runs. Two tests, because the gap has two halves and each fails differently: one drives the
# new branch, one pins the column constraint that currently hides it.
# ---------------------------------------------------------------------------

PROBE_FN = "task_transition_null_stored_token_probe"
PROBE_ARGTYPES = "bigint, text, bigint, jsonb, text"
# The single statement in the shipped body that binds the stored token. It is unique, which is
# what makes the substitution below verifiable instead of hoped for.
BIND_MARKER = "v_found := found;"


class _RollbackProbe(Exception):
    """Raised only to force the probe transaction to roll back, so neither the probe function
    nor anything it wrote can outlive the test."""


async def _installable_null_stored_token_probe(conn):
    """SQL that installs a clone of `task_transition` whose stored token reads NULL.

    The clone is assembled from `pg_proc.prosrc` — the body Postgres actually compiled for the
    shipped function — plus one injected assignment. That choice is the whole point: a
    hand-written copy of the guard chain would keep passing after any edit to 0002 and so would
    prove nothing about the code under review. Derived from the catalog, every guard, every
    reason code and every `return;` terminator exercised here IS 0002's, with exactly one
    different input value.
    """
    src = await conn.fetchval("select prosrc from pg_proc where proname='task_transition'")
    assert src is not None, "task_transition is not installed, so there is no body to clone"
    assert src.count(BIND_MARKER) == 1, \
        f"{BIND_MARKER!r} occurs {src.count(BIND_MARKER)} times — the substitution target is ambiguous"
    assert "v_token := null" not in src, \
        "the shipped body already forces the stored token to NULL; this probe is no longer a probe"

    patched = src.replace(BIND_MARKER, BIND_MARKER + "\n  v_token := null;", 1)
    assert patched.count("v_token := null;") == 1, "the substitution did not apply"
    return (
        f"create function {PROBE_FN}(p_task_id bigint, p_to_state text, p_token bigint,\n"
        f"                            p_evidence jsonb, p_actor text)\n"
        f"returns table(ok boolean, reason text, new_state text) as $probe_body$\n"
        f"{patched}\n$probe_body$ language plpgsql"
    )


async def test_a_null_stored_token_fails_closed(conn):
    """The fence must refuse a row that has no token to check, not authorise it.

    Measured by review on this function's own body with `v_token := null`: reason=OK, the state
    advanced, an OK audit row was written and an outbox event queued — a sole writer that
    waves through an uncheckable token is not a fence. The stored side is unreachable from
    `tasks` today because 0001 declares `fencing_token bigint not null default 0`, so rather
    than fake a row that cannot be inserted, the probe drives the shipped body with that one
    variable forced NULL.

    Deleting the `v_token is null` branch from 0002 turns THIS red: the comparison falls open,
    CREATED->PLANNED is a declared edge, so the probe reports OK and moves the state.
    test_the_stored_token_column_is_declared_not_null is the other half — it turns red if the
    column is ever relaxed instead."""
    tid = await seed(conn)  # CREATED, stored token 0; CREATED->PLANNED is a legal edge
    ddl = await _installable_null_stored_token_probe(conn)

    try:
        async with conn.transaction():
            await conn.execute(ddl)
            rows = await conn.fetch(
                f"select * from {PROBE_FN}($1,$2,$3,$4::jsonb,$5)", tid, "PLANNED", 0, None, "probe")

            assert len(rows) == 1, \
                f"{len(rows)} rows from one refusal — execution fell through the stored-token guard"
            assert (rows[0]["ok"], rows[0]["reason"]) == (False, "BAD_TOKEN"), \
                "a NULL stored token authorised the transition: the fence fell open"
            assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED", \
                "the fall-open write moved tasks.state"
            assert await conn.fetchval("select count(*) from outbox_events") == 0, \
                "the fall-open write queued an outbox event"
            assert await conn.fetchval("select count(*) from audit_events where outcome='OK'") == 0, \
                "the fall-open write signed its own OK audit row"
            assert await conn.fetchval(
                "select count(*) from audit_events "
                "where outcome='BAD_TOKEN' and target=$1 and actor='probe'", str(tid)) == 1, \
                "the stored-side rejection was not audited"
            raise _RollbackProbe("roll the probe back so no probe object survives")
    except _RollbackProbe:
        pass
    finally:
        await conn.execute(f"drop function if exists {PROBE_FN}({PROBE_ARGTYPES})")

    # From outside the rolled-back transaction: the probe is gone and nothing it touched stays.
    assert await conn.fetchval("select count(*) from pg_proc where proname=$1", PROBE_FN) == 0, \
        f"probe function {PROBE_FN} leaked into the schema"
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval("select count(*) from audit_events") == 0, "probe left an audit row"
    assert await conn.fetchval("select count(*) from outbox_events") == 0, "probe left an event"

async def test_the_stored_token_column_is_declared_not_null(conn):
    """Pin the constraint that currently makes the NULL-stored-token branch dead code.

    The branch holds shut today for one reason only: `tasks.fencing_token` is NOT NULL, so no
    INSERT can put a NULL in the column the guard reads. Nothing in the function's own text
    records that, which is exactly the "unreachable by accident" gap review named — an
    `alter table tasks alter column fencing_token drop not null` in some future migration (to
    let a task row exist before its token is minted, say) would make the path reachable again
    and reopen the fence silently. This test makes that migration fail the suite the day it
    lands, instead of leaving it to be discovered by whoever still remembers T3-A.

    Asserted twice, because a declaration is worth only what its enforcement is: the catalog
    metadata, and a live NULL insert that Postgres actually refuses."""
    is_nullable = await conn.fetchval(
        "select is_nullable from information_schema.columns "
        "where table_name='tasks' and column_name='fencing_token'")
    assert is_nullable == "NO", (
        f"tasks.fencing_token is_nullable={is_nullable!r} — the stored-token NULL branch in "
        "0002_transition.sql is now the only thing holding that fence shut. Do not delete it.")

    await seed(conn)
    with pytest.raises(asyncpg.exceptions.NotNullViolationError):
        await conn.execute(
            "insert into tasks(prompt_id,role_id,objective,state,fencing_token) "
            "values('p1','r1','o','CREATED',null)")
