from authority.fencing import bump_token
from authority.transitions import task_transition

async def seed(conn):
    """DEFECT FOUND IN THE BRIEF. As written, `seed` inserted the two head rows on every
    call, so `test_tokens_never_reused_across_tasks` — the one test that seeds two tasks —
    died with `duplicate key value violates unique constraint "prompts_pkey"` before any
    assertion ran. The heads are now `on conflict do nothing`, which is the same fix
    `tests/test_transitions.py`'s seed needed for the identical reason; the assertions below
    are the brief's, apart from one parenthesisation fix recorded in
    test_tokens_never_reused_across_tasks."""
    await conn.execute("insert into prompts(id) values('p1') on conflict (id) do nothing")
    await conn.execute(
        "insert into roles(id,name,profile_version) values('r1','T',1) on conflict (id) do nothing")
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective) values('p1','r1','o') returning id")

async def test_stale_token_cannot_write_even_on_a_legal_edge(conn):
    tid = await seed(conn)
    await bump_token(conn, tid)                        # holder was granted at token 0
    res = await task_transition(conn, tid, "PLANNED", 0, None, "zombie")
    assert (res.ok, res.reason) == (False, "BAD_TOKEN")
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"

async def test_current_token_writes(conn):
    tid = await seed(conn)
    tok = await bump_token(conn, tid)
    assert (await task_transition(conn, tid, "PLANNED", tok, None, "holder")).ok is True

async def test_tokens_are_monotonic_per_task(conn):
    tid = await seed(conn)
    seen = [await bump_token(conn, tid) for _ in range(5)]
    assert seen == sorted(seen) and len(set(seen)) == 5

async def test_tokens_never_reused_across_tasks(conn):
    """Non-reuse comes from ONE global sequence, not from the mechanism the brief's Step-4
    note claimed. It asserted that `nextval` is evaluated even by an UPDATE matching zero
    rows; that is false — measured, two zero-row UPDATEs left `last_value` at 1 and the
    next mint was 2, so a bump against a missing task mints nothing and burns nothing.
    What actually guarantees a token is never handed to two tasks is that
    `fencing_token_seq` is one schema-global sequence and `nextval` never repeats a value
    inside a sequence's lifetime, so task B's stored token can never equal task A's."""
    a, b = await seed(conn), await seed(conn)
    ta = await bump_token(conn, a)
    tb = await bump_token(conn, b)
    assert ta != tb
    # DEFECT FOUND IN THE BRIEF (second one in this test). `await f(...).ok` parses as
    # `await (f(...).ok)` — `await` binds looser than `.` — so the brief's line reached for
    # `.ok` on an un-awaited coroutine and died with `AttributeError: 'coroutine' object has
    # no attribute 'ok'`. Parenthesised here exactly as the brief's own
    # test_current_token_writes already does; the assertion is unchanged.
    assert (await task_transition(conn, b, "PLANNED", ta, None, "crossed")).ok is False

async def test_bump_on_a_missing_task_returns_none(conn):
    assert await bump_token(conn, 123456) is None


# ---------------------------------------------------------------------------
# Proofs the dispatch asked for but the brief did not contain. Each one below exists
# because a claim about this mechanism was asserted somewhere and not measured.
# ---------------------------------------------------------------------------

async def test_the_app_role_can_mint_and_store_a_fencing_token(conn):
    """Ruling T4-1 (Task 4 dispatch) — the sequence grant, proven by running the statement
    rather than by a privilege flag, the convention test_schema.py adopted after P-6.

    `0001_schema.sql`'s `grant usage, select on all sequences in schema public` is
    POINT-IN-TIME: it reaches only sequences that already exist when it runs, and
    `fencing_token_seq` is created after it, by this task's own `0003_fencing.sql`. Without
    an explicit grant in 0003, `authority_app` cannot call `next_fencing_token()` — and
    because every test in this suite connects as the cluster superuser, nothing else
    notices: the brief's five tests were measured green with no grant at all. Task 6's
    `claim_lease()` mints inside that role's session, so this is the difference between a
    deployable authority and one that dies on its first lease.

    Both halves are required and both are in one session: the succeeding half (mint +
    store) proves the role was really assumed and can operate the column. The negative
    control is not a test but a measurement, because a committed test that revokes a
    cluster-persistent role's privilege is a leak risk: withdrawing 0003's grant inside a
    transaction that is then rolled back makes this same call die with
    InsufficientPrivilegeError, which is what makes the grant load-bearing rather than
    decorative (P-9's lesson)."""
    tid = await seed(conn)

    await conn.execute("set role authority_app")
    assert await conn.fetchval("select current_user") == "authority_app", \
        "SET ROLE did not take, so the assertions below would prove nothing"

    minted = await conn.fetchval("select next_fencing_token()")
    assert isinstance(minted, int) and minted > 0, "the app role cannot mint a token"
    again = await conn.fetchval("select next_fencing_token()")
    assert again > minted, "the app role's mints are not monotonic"

    # The end-to-end path Task 6 will use: bump_token = UPDATE tasks + nextval, both of
    # which the declared role must hold (ruling P-6 granted the UPDATE, T4 grants the
    # sequence). A gap in either half fails here rather than at a lease claim.
    stored = await bump_token(conn, tid)
    assert isinstance(stored, int) and stored > again
    assert await conn.fetchval("select fencing_token from tasks where id=$1", tid) == stored

async def test_the_sequence_starts_above_the_column_default(conn):
    """Ruling T4-2: `tasks.fencing_token` keeps `not null default 0`, so 0 is the value a
    never-granted holder carries, and the very first token this sequence can hand out must
    be above it or the two would be indistinguishable and the zombie test's token 0 would
    collide with a real grant. Measured on a fresh schema, where this bump is the
    sequence's first call."""
    tid = await seed(conn)
    assert await conn.fetchval(
        "select column_default from information_schema.columns "
        "where table_name='tasks' and column_name='fencing_token'") == "0"
    assert await conn.fetchval("select fencing_token from tasks where id=$1", tid) == 0
    assert await bump_token(conn, tid) == 1, \
        "fencing_token_seq no longer starts strictly above the column default of 0"

async def test_a_missing_task_burns_no_sequence_value(conn):
    """The brief's Step-4 note claimed the opposite of this — that `nextval` fires even for
    the UPDATE matching zero rows, so a failed bump would still consume a value. Measured:
    it does not (a zero-row UPDATE evaluates no SET expression at all), which is what this
    pins via the gap between two real mints rather than by reading `last_value`: if the
    missing-task bump had burned a value the second mint would be first + 2."""
    tid = await seed(conn)
    first = await bump_token(conn, tid)
    assert await bump_token(conn, 123456) is None
    assert await bump_token(conn, tid) == first + 1, \
        "a bump that stored nothing still consumed a sequence value"

async def test_a_bump_refreshes_updated_at(conn):
    """Self-review found this as a surviving mutant and closed it rather than documenting it.

    `bump_token`'s UPDATE carries `updated_at = now()`, and nothing in this task's tests read
    that column: measured, deleting the term left the whole suite green (41 passed), so the
    statement was half-decoration. Lease/TTL reasoning reads freshness off this column, so a
    bump that moved the token but not the timestamp is a real failure mode, not a style issue.

    `updated_at` is pinned to a fixed past instant first rather than compared to its own
    previous value, because `now()` is the TRANSACTION timestamp and two implicit transactions
    in the same microsecond would make a bare `>` comparison flaky."""
    tid = await seed(conn)
    await bump_token(conn, tid)
    await conn.execute(
        "update tasks set updated_at = timestamp with time zone '2000-01-01T00:00:00+00' "
        "where id = $1", tid)

    await bump_token(conn, tid)
    assert await conn.fetchval(
        "select updated_at > now() - interval '1 hour' from tasks where id=$1", tid) is True, \
        "bump_token stopped touching updated_at"

