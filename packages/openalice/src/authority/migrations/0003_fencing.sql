-- Task 4: monotonic fencing tokens — the mechanism that makes a stale lease holder inert.
--
-- Deviation 2 (kept from the brief, and it is the right call): ONE global sequence rather
-- than a per-task counter. A per-task counter needs a read-modify-write on `tasks` to be
-- monotonic, which is exactly the race Task 5 proves; a global sequence is monotonic by
-- construction, so two tasks can never be handed the same token and a token minted for one
-- task can never be replayed against another. `next_fencing_token()` is the only door.
--
-- `tasks.fencing_token` stays `bigint not null default 0` exactly as 0001 declared it
-- (ruling T4-2). Nothing here mints a NULL, relaxes the column, or writes a token any other
-- way — `alter column ... drop not null` would reopen ruling T3-A's stored-side hole, and
-- tests/test_transitions.py::test_the_stored_token_column_is_declared_not_null turns red the
-- day anyone tries. The sequence starts at 1, strictly above that default, so the 0 a
-- never-granted holder carries is never a value the authority actually issued
-- (pinned by test_the_sequence_starts_above_the_column_default).
--
-- No id-existence guard is needed here, unlike the `authority_app` role in 0001: roles are
-- CLUSTER-scoped and survive the fixture's `drop schema public cascade`, but a sequence lives
-- inside `public` and is dropped with it, so every re-application creates it from nothing.
-- Measured rather than assumed. The fixture re-applies all three files on every test that takes
-- a connection, so a single suite run creates and drops this sequence once per such test; two
-- back-to-back manual migration passes on the same cluster state end each time with `count(*)=1`
-- for both the sequence and the function, 6 sequences in `public`, the app-role grant intact and
-- the sequence restarted at 1 — no DuplicateObjectError anywhere. Two consecutive full-suite
-- runs were then taken on this file exactly as it stands.
--
-- `SECURITY DEFINER` is deliberately absent, as it is everywhere in Plan 1 (ruling P-6): this
-- function runs as its caller, so the caller's own sequence privilege is what gates a mint.
-- That is why the grant below is not decoration. It also means the unqualified
-- `nextval('fencing_token_seq')` resolves through the CALLER's search_path; every path in
-- Plan 1 uses the default `"$user", public`, and Plan 3 must pin a search_path if it ever
-- makes this a definer-side function.

create sequence fencing_token_seq;

-- Ruling T4-1, and — unlike correction T2-E's premise, which turned out to be
-- order-insurance — this one is genuinely load-bearing. 0001's
-- `grant usage, select on all sequences in schema public to authority_app` is POINT-IN-TIME:
-- `all sequences in schema public` expands at the moment that statement runs, and this
-- sequence does not exist until 0003 executes after it. Without the line below the declared
-- application role cannot mint a token at all: measured live, `has_sequence_privilege` reads
-- false for both USAGE and SELECT, `SET ROLE authority_app; select next_fencing_token()`
-- dies with `permission denied for sequence fencing_token_seq`, and every one of this task's
-- brief-authored tests still passes — because the suite connects as the cluster superuser,
-- the same blind spot that made P-6 and P-9 near-invisible. Task 6's `claim_lease()` bumps
-- the token from inside the app role's session, so this grant is the difference between a
-- deployable authority and one that fails its first lease.
--
-- `usage` is what nextval() checks; `select` is included so the role can read `last_value`
-- for diagnosis, matching 0001's blanket grant shape rather than inventing a narrower one.
-- EXECUTE on the function itself needs no grant — Postgres gives PUBLIC execute on a new SQL
-- function, and this is the privilege that must NOT be widened, since the function's power is
-- bounded by the caller's sequence access. Evidence for that reading: the pre-grant failure
-- below was `permission denied for sequence fencing_token_seq`, never `... for function
-- next_fencing_token`, so the app role was already reaching the body and only the sequence
-- stopped it.
grant usage, select on sequence fencing_token_seq to authority_app;

create or replace function next_fencing_token() returns bigint as
  $$ select nextval('fencing_token_seq') $$ language sql;
