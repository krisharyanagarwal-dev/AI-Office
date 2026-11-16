import asyncpg

LEGAL_STATES = {"CREATED", "PLANNED", "APPROVED", "QUEUED", "RUNNING",
                "VERIFYING", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED",
                "QUARANTINED"}

async def _seed_heads(conn):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")

async def _seed_task(conn, objective="o"):
    """Callers seed the heads once, then pull as many CREATED tasks as they need."""
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective,state) values('p1','r1',$1,'CREATED') returning id",
        objective)

async def test_every_lifecycle_state_is_declared(conn):
    rows = await conn.fetch(
        "select from_state s from state_edges union select to_state s from state_edges")
    assert {r["s"] for r in rows} == LEGAL_STATES

async def test_cancellation_is_declared_from_every_non_terminal_state(conn):
    """Ruling T2-C: spec §17.7 asks for cancellation at each state. BLOCKED is
    non-terminal — it re-enters QUEUED — so it is cancellable too, and the equality
    also pins that the four terminal states cannot reach CANCELLED."""
    rows = await conn.fetch(
        "select from_state s from state_edges where to_state = 'CANCELLED'")
    assert {r["s"] for r in rows} == {"CREATED", "PLANNED", "APPROVED", "QUEUED",
                                      "RUNNING", "VERIFYING", "BLOCKED"}

async def test_undocumented_state_is_rejected(conn):
    await _seed_heads(conn)
    try:
        await conn.execute(
            "insert into tasks(prompt_id,role_id,objective,state) values('p1','r1','o','HAPPY')")
    except asyncpg.exceptions.RaiseError as e:
        assert "undocumented task state" in e.message
    else:
        raise AssertionError("HAPPY accepted — spec §5 invariant 1 is not enforced")

async def test_documented_state_inserts(conn):
    await _seed_heads(conn)
    n = await conn.execute(
        "insert into tasks(prompt_id,role_id,objective,state) values('p1','r1','o','CREATED')")
    assert n.endswith("1")

async def test_a_task_records_a_dependency_and_cannot_depend_on_itself(conn):
    """Ruling T2-E: master §5 lists Dependencies per task, as a task<->task edge table.

    The valid non-self edge is inserted first and must succeed, so the rejection below
    can only be the `task_id <> depends_on_task_id` CHECK firing — not a missing table,
    a broken FK, or a privilege gap. That pairing is mandatory: P-9's defect in this
    very file was a negative assertion whose positive half never worked. Cycles stay
    unguarded by design (a cycle check is a recursive query at admission time, which is
    Plan 2's scheduler), so this test deliberately does not pretend otherwise."""
    await _seed_heads(conn)
    downstream = await _seed_task(conn, "build")
    upstream = await _seed_task(conn, "measure")

    assert (await conn.execute(
        "insert into task_dependencies(task_id,depends_on_task_id) values($1,$2)",
        downstream, upstream)).endswith("1")
    assert await conn.fetchval(
        "select count(*) from task_dependencies where task_id=$1 and depends_on_task_id=$2",
        downstream, upstream) == 1

    try:
        await conn.execute(
            "insert into task_dependencies(task_id,depends_on_task_id) values($1,$1)",
            downstream)
    except asyncpg.exceptions.CheckViolationError as e:
        assert e.sqlstate == "23514"
        assert "task_dependencies_check" in e.message, \
            f"rejected by something other than the self-dependency CHECK: {e.message}"
    else:
        raise AssertionError("a task was allowed to depend on itself — T2-E's CHECK is not enforced")

async def test_evidence_rows_carry_a_producer_and_start_unverified(conn):
    """Ruling T2-E: master §5's Execution evidence, column-for-column against spec §5's
    data model (producer slot, kind, payload ref, sha256 digest, verdict). `verdict`
    reads back NULL because the producer wrote the row and nobody has verified it yet —
    exactly the distinction Task 3's evidence-bearing edges (RUNNING->VERIFYING,
    VERIFYING->COMPLETED) have to be able to see."""
    await _seed_heads(conn)
    await conn.execute("insert into worker_slots(id,adapter) values('s1','codex')")
    task_id = await _seed_task(conn)
    evidence_id = await conn.fetchval(
        "insert into task_evidence(task_id,produced_by_slot,kind,payload_ref,sha256) "
        "values($1,'s1','diff','runs/1.diff','ab12cd34') returning id", task_id)
    row = await conn.fetchrow("select * from task_evidence where id=$1", evidence_id)
    assert row["task_id"] == task_id
    assert row["produced_by_slot"] == "s1"
    assert row["kind"] == "diff"
    assert row["payload_ref"] == "runs/1.diff"
    assert row["sha256"] == "ab12cd34"
    assert row["produced_at"] is not None
    assert row["verdict"] is None, "evidence arrived already verified — nothing verified it"
    assert row["verified_by"] is None and row["verified_at"] is None

async def test_audit_events_cannot_be_updated_by_the_app_role(conn):
    await conn.execute(
        "insert into audit_events(actor,action,target,outcome) values('t','x','1','OK')")
    await conn.execute("set role authority_app")
    try:
        await conn.execute("update audit_events set outcome='LOOKED_FINE'")
    except asyncpg.exceptions.InsufficientPrivilegeError:
        pass
    else:
        raise AssertionError("audit trail is rewritable — spec §15 append-only claim is false")

async def test_the_denial_is_a_privilege_denial_not_a_missing_object(conn):
    """Positive control for the append-only test above. If `audit_events` were
    invisible to authority_app, its UPDATE would fail with UndefinedTableError, the
    role would never have been assumed at all, and the append-only test would pass
    for the wrong reason. Here the role demonstrably sees the table, inserts into it,
    and still cannot update it — and the revocation is pinned directly, so a dropped
    revoke cannot hide behind a grant that was never there."""
    assert await conn.fetchval("select to_regclass('audit_events') is not null") is True
    assert await conn.fetchval(
        "select has_table_privilege('authority_app','audit_events','insert')") is True
    for denied in ("update", "delete", "truncate"):
        assert await conn.fetchval(
            "select has_table_privilege('authority_app','audit_events',$1::text)",
            denied) is False, f"authority_app still holds {denied.upper()}"
    await conn.execute("set role authority_app")
    await conn.execute(
        "insert into audit_events(actor,action,target,outcome) values('app','x','1','OK')")
    assert await conn.fetchval("select count(*) from audit_events") == 1

async def test_the_app_role_updates_what_it_operates_and_still_not_audit(conn):
    """Ruling P-6 positive control — both halves, same role, same session.

    The succeeding half is what makes the failing half mean anything: if this role
    could not UPDATE *anything* — because it was never granted, or because the session
    never really changed user — `update audit_events` would fail for the wrong reason
    and the append-only claim would be decoration again, which is exactly the failure
    mode P-9 caught. So the three tables the application legitimately writes (Task 3
    bumps tasks, Task 6 renews/releases leases, Task 7's drain sets
    outbox_events.published_at) must accept an UPDATE from authority_app, and
    audit_events must still refuse one.

    The audit denial is proven by attempting the statement, not by a privilege pin —
    the direct `has_table_privilege` pin lives in
    test_the_denial_is_a_privilege_denial_not_a_missing_object above.
    """
    await _seed_heads(conn)
    await conn.execute("insert into worker_slots(id,adapter) values('s1','mock')")
    task_id = await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective,state) values('p1','r1','o','CREATED') returning id")
    await conn.execute(
        "insert into leases(task_id,slot_id,fencing_token,expires_at) values($1,'s1',1,now() + interval '1 hour')",
        task_id)
    event_id = await conn.fetchval(
        "insert into outbox_events(prompt_id,task_id,event_type,dedupe_key) values('p1',$1,'task.created',$2) returning id",
        task_id, f"t{task_id}.created")
    await conn.execute(
        "insert into audit_events(actor,action,target,outcome) values('t','x','1','OK')")

    for table in ("tasks", "leases", "outbox_events"):
        assert await conn.fetchval(
            "select has_table_privilege('authority_app',$1::text,'update')", table) is True, \
            f"authority_app cannot UPDATE {table} — the declared role cannot operate the schema"

    await conn.execute("set role authority_app")
    # The half that must succeed. `priority` (not `state`) keeps the state trigger out
    # of the picture: this asserts a privilege, not a transition.
    assert (await conn.execute(
        "update tasks set priority = priority where id = $1", task_id)).endswith("1")
    assert (await conn.execute(
        "update leases set renewed_at = now() where task_id = $1", task_id)).endswith("1")
    assert (await conn.execute(
        "update outbox_events set published_at = now() where id = $1", event_id)).endswith("1")

    # The half that must fail, in the same session that just proved UPDATE works here.
    try:
        await conn.execute("update audit_events set outcome='LOOKED_FINE' where id = ("
                           "select min(id) from audit_events)")
    except asyncpg.exceptions.InsufficientPrivilegeError:
        pass
    else:
        raise AssertionError("audit trail is rewritable by the app role — spec §15 append-only claim is false")

async def test_the_app_role_writes_dependencies_and_evidence(conn):
    """Ruling T2-E privileges, proven by running the statements rather than only by a
    privilege flag — the convention this file adopted for the append-only control after
    P-6, because a flag proves a grant exists while the statement proves the role can
    actually operate the table. authority_app admits a dependency edge, inserts an
    evidence row and sets a verdict on it.

    Withdrawing the two table grants makes this die with InsufficientPrivilegeError
    (measured, not assumed). Withdrawing only the explicit task_evidence_id_seq grant
    does NOT fail today — the blanket `all sequences in schema public` line in the
    migration already reaches a sequence created above it — so this test does not claim
    to be that grant's proof; the explicit grant is order-independent insurance for the
    sequences 0002 will add. Neither new table holds DELETE or TRUNCATE, withheld by
    omission exactly as on outbox_events, so the writes below are the only ones the role
    makes here."""
    await _seed_heads(conn)
    await conn.execute("insert into worker_slots(id,adapter) values('s1','codex')")
    downstream = await _seed_task(conn, "build")
    upstream = await _seed_task(conn, "measure")

    await conn.execute("set role authority_app")
    assert (await conn.execute(
        "insert into task_dependencies(task_id,depends_on_task_id) values($1,$2)",
        downstream, upstream)).endswith("1")
    evidence_id = await conn.fetchval(
        "insert into task_evidence(task_id,produced_by_slot,kind,payload_ref,sha256) "
        "values($1,'s1','test-log','runs/1.log','ab12cd34') returning id", upstream)
    assert (await conn.execute(
        "update task_evidence set verdict='PASS' where id=$1", evidence_id)).endswith("1")
    assert await conn.fetchval(
        "select verdict from task_evidence where id=$1", evidence_id) == "PASS"

async def test_redact_scrubs_every_known_credential_shape(conn):
    cases = [
        "nvapi-AbCdEf1234567890ghiJKLMNOP",
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "github_pat_11ABCDEFG0abcdefghijklMN",
        "Bearer zzzz-very-secret-token-value",
    ]
    for secret in cases:
        out = await conn.fetchval("select redact($1::jsonb)", f'{{"k":"{secret}"}}')
        assert secret not in out, f"{secret[:8]}… survived redaction"
        assert "<redacted>" in out

async def test_redact_leaves_ordinary_values_alone(conn):
    out = await conn.fetchval("select redact($1::jsonb)", '{"state":"RUNNING","count":3}')
    assert "RUNNING" in out and "3" in out
    # Ruling T2-A: the credential shapes are prefix-anchored, so a bare `sk` inside a
    # word no longer matches. These are the task.* event names audit and outbox
    # payloads are built from; an unanchored `sk` scrubbed each one to `ta<redacted>`.
    for value in ("task_created", "task_created_event", "asked_question_here"):
        out = await conn.fetchval("select redact($1::jsonb)", f'{{"ev":"{value}"}}')
        assert value in out, f"{value} was scrubbed — redact() over-matches ordinary text"
        assert "<redacted>" not in out, f"{value} was rewritten by the credential pattern"
