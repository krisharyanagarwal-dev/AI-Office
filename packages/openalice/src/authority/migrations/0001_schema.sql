-- Task 2: base schema, declared state vocabulary, the state trigger, redact(),
-- and the append-only-proven application role.
--
-- Everything here is re-applied on every test session (tests/conftest.py drops and
-- recreates schema `public` first), which is why the only cluster-scoped statement
-- in the file — role creation — sits inside an idempotency guard (ruling P-5).

create table prompts(
  id text primary key, source text not null default 'chat',
  submitted_at timestamptz not null default now(), actor text, status text,
  trace_id text
);

create table roles(
  id text primary key, name text not null, capability_profile jsonb not null default '{}',
  profile_version int not null default 1, status text not null default 'ACTIVE',
  retired_at timestamptz, tombstone_at timestamptz,
  unique(id, profile_version)
);

create table worker_slots(
  id text primary key, adapter text not null, external_ref text,
  state text not null default 'UNKNOWN',
  verified_at timestamptz, last_seen_at timestamptz, probe_run_id text
);

create table state_edges(
  from_state text not null, to_state text not null,
  requires_evidence boolean not null default false,
  retryable boolean not null default false,
  primary key(from_state, to_state)
);

create table tasks(
  id bigserial primary key,
  prompt_id text not null references prompts(id),
  role_id text not null references roles(id),
  objective text not null,
  priority int not null default 5,
  repo text, base_commit text,
  allowed_paths jsonb not null default '[]',
  prohibited_paths jsonb not null default '[]',
  allowed_ops jsonb not null default '[]',
  prohibited_ops jsonb not null default '[]',
  acceptance jsonb not null default '{}',
  verification jsonb not null default '{}',
  limits jsonb not null default '{}',
  state text not null default 'CREATED',
  fencing_token bigint not null default 0,
  assigned_slot_id text references worker_slots(id),
  worktree_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);
create index on tasks(state);
create index on tasks(prompt_id);

-- Ruling T2-E: master §5 requires every task to carry "Dependencies" and "Execution
-- evidence"; Task 2's first pass had neither. Dependencies are a task<->task edge table
-- and NOT a jsonb column on tasks, because "are this task's dependencies satisfied" has
-- to be a query a scheduler can run, not a document it has to parse. The CHECK blocks a
-- task depending on itself.
-- Known limit, deliberately not implemented here: dependency CYCLES are unguarded —
-- detecting one needs a recursive query at admission time, which is Plan 2's scheduler.
create table task_dependencies(
  task_id bigint not null references tasks(id),
  depends_on_task_id bigint not null references tasks(id),
  primary key(task_id, depends_on_task_id),
  check(task_id <> depends_on_task_id)
);
create index on task_dependencies(depends_on_task_id);

-- Execution evidence, column-for-column against spec §5's data model: producer slot,
-- kind, payload ref, sha256 digest, verdict. verdict/verified_by/verified_at are
-- nullable because the producer writes the row long before anyone verifies it, and Task
-- 3's evidence-bearing edges have to be able to tell those two states apart.
create table task_evidence(
  id bigserial primary key,
  task_id bigint not null references tasks(id),
  produced_by_slot text references worker_slots(id),
  produced_at timestamptz not null default now(),
  kind text not null,
  payload_ref text,
  sha256 text,
  verdict text,
  verified_by text,
  verified_at timestamptz
);
create index on task_evidence(task_id);

create table leases(
  task_id bigint primary key references tasks(id),
  slot_id text not null references worker_slots(id),
  fencing_token bigint not null,
  acquired_at timestamptz not null default now(),
  expires_at timestamptz not null,
  renewed_at timestamptz,
  released_at timestamptz,
  released_reason text
);

-- Declared now so Plan 2 never alters a live schema. Plan 1 allocates no rows here.
create table worktrees(
  id text primary key, repo text not null, base_commit text not null,
  path text not null, state text not null default 'FREE',
  leased_to_task bigint references tasks(id),
  allocated_at timestamptz, reaped_at timestamptz, size_bytes bigint
);
create table merge_queue(
  seq bigserial primary key, task_id bigint references tasks(id),
  worktree_id text references worktrees(id), state text not null default 'QUEUED',
  attempted_at timestamptz, outcome text
);

create table outbox_events(
  id bigserial primary key, prompt_id text, task_id bigint, event_type text not null,
  payload jsonb not null default '{}',
  emitted_at timestamptz not null default now(), published_at timestamptz,
  dedupe_key text not null unique
);
create index on outbox_events(published_at) where published_at is null;

create table audit_events(
  id bigserial primary key, at timestamptz not null default now(),
  actor text, action text not null, target text,
  before_state text, after_state text, fencing_token bigint,
  redacted_payload jsonb not null default '{}', outcome text
);

-- Deviation 1 (spec §5 invariant 1): a CHECK cannot subquery, so this trigger is
-- what makes "no undocumented state" real rather than aspirational.
create or replace function reject_undocumented_state() returns trigger as $$
begin
  if not exists (
    select 1 from (select from_state s from state_edges
                   union select to_state s from state_edges) d
    where d.s = new.state
  ) then
    raise exception 'undocumented task state: %', new.state;
  end if;
  return new;
end $$ language plpgsql;

create trigger tasks_state_is_documented
  before insert or update of state on tasks
  for each row execute function reject_undocumented_state();

-- Spec §12: scrub before anything reaches audit, logs, or a report. Shapes cover
-- what actually exists in this fleet's ~/.env plus the historical leaks in spec §3.
-- Built on text: Postgres has no jsonb regex function, so jsonb casts through text.
-- Ruling T2-A: each shape carries its literal prefix and one word-start anchor. An
-- unanchored `sk` matched inside ordinary snake_case text — `task_created_event`
-- came back as `ta<redacted>` and `asked_question_here` as `a<redacted>` — and audit
-- and outbox payloads are built from exactly those task.* names, so the scrubber was
-- corrupting the records spec §12 requires to stay readable. Prefix-plus-\m keeps all
-- five credential shapes fatal and leaves the vocabulary alone.
create or replace function redact(p jsonb) returns jsonb as $$
  select regexp_replace(
           regexp_replace(p::text,
             '\m(nvapi-|sk-|ghp_|gho_|github_pat_)[A-Za-z0-9_\-]{8,}', '<redacted>', 'g'),
           '(?i)(bearer +)[A-Za-z0-9._\-]+', '\1<redacted>', 'g'
         )::jsonb
$$ language sql;

-- Deviation 3: append-only proven by a real non-superuser role.
-- Ruling P-5: roles are CLUSTER-scoped, but the test fixture recreates schema
-- `public` on every run, so this one statement must be idempotent or the second
-- test run of every later task dies on a duplicate-object error. Only the role is
-- guarded — the grants below must re-run every pass, because a freshly created
-- `public` schema arrives with no grants on it.
-- The brief's option list said `nocreate`; Postgres rejects that outright
-- ("unrecognized role option"), so the two options it stood for are spelled out.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authority_app') THEN
    CREATE ROLE authority_app nosuperuser nocreaterole nocreatedb nologin;
  END IF;
END $$;

grant usage on schema public to authority_app;
grant select, insert on tasks, prompts, roles, worker_slots, state_edges,
                       leases, outbox_events, audit_events, worktrees, merge_queue
  to authority_app;
grant usage, select on all sequences in schema public to authority_app;

-- Ruling P-6: least-privilege UPDATE on the three tables the application itself
-- writes. Task 3 bumps tasks.state/fencing_token, Task 6 renews and releases leases,
-- and Task 7's outbox drain sets outbox_events.published_at. A role that holds only
-- select+insert cannot operate the schema it declares, and because every test runs as
-- the postgres superuser nothing in the suite would ever have noticed. UPDATE only —
-- no DELETE, no TRUNCATE, and no write privilege on audit_events beyond INSERT.
-- `SECURITY DEFINER` is deliberately not used here: it is deferred to Plan 3, where it
-- must arrive with a pinned search_path or it becomes an escalation surface.
grant update on tasks, leases, outbox_events to authority_app;

-- Ruling T2-E: task_dependencies and task_evidence take the same operational posture as
-- tasks / leases / outbox_events — the application admits a dependency edge and writes an
-- evidence row, so select + insert + update. DELETE and TRUNCATE stay withheld by
-- omission, exactly as they are on outbox_events, and audit_events' grant-then-revoke
-- posture below is untouched.
-- Which half actually bites is measured, not assumed. The TABLE grant is load-bearing
-- today: withdraw it and the app-role test dies with InsufficientPrivilegeError. The
-- SEQUENCE grant is written explicitly because the blanket `all sequences in schema
-- public` line above is POINT-IN-TIME — it reaches only sequences that already exist
-- when it runs, so it can say nothing about one created after it, which is exactly what
-- Task 4's fencing_token_seq will be when 0002 lands. Stated honestly: deleting just
-- this sequence line changes nothing observable today, because task_evidence_id_seq is
-- created earlier in this file and the blanket line already reaches it. It is here as
-- the pattern that survives that ordering, not as a privilege nothing else provides.
grant select, insert, update on task_dependencies, task_evidence to authority_app;
grant usage, select on task_evidence_id_seq to authority_app;

-- Deviation 3 says the revocation below must *bite*, and a revoke of a privilege
-- that was never granted bites nothing — it is a no-op, and Task 11's
-- "append-only revoke dropped" mutant would find this suite decorative. So the
-- append-only table is granted its normal write privileges and then stripped of them,
-- in one file, in that order. Net ACL for authority_app on audit_events is unchanged:
-- select + insert only. The difference is that the deny is now load-bearing and
-- testable. (P-9 also paired this with outbox_events; that pairing is gone by ruling
-- P-6, because Task 7's drain legitimately needs UPDATE there — the old revoke
-- contradicted the design rather than protecting anything. DELETE and TRUNCATE on
-- outbox_events are withheld by the narrower grant above.)
grant update, delete, truncate on audit_events to authority_app;
revoke update, delete, truncate on audit_events from authority_app;

insert into state_edges(from_state,to_state,requires_evidence,retryable) values
  ('CREATED','PLANNED',false,false),   ('PLANNED','APPROVED',false,false),
  ('APPROVED','QUEUED',false,false),   ('QUEUED','RUNNING',false,false),
  ('RUNNING','VERIFYING',true,false),  ('VERIFYING','COMPLETED',true,false),
  ('CREATED','CANCELLED',false,false), ('PLANNED','CANCELLED',false,false),
  ('APPROVED','CANCELLED',false,false),('QUEUED','CANCELLED',false,false),
  ('RUNNING','CANCELLED',false,false), ('VERIFYING','CANCELLED',false,false),
  -- Ruling T2-C: BLOCKED is non-terminal (§17.7 cancellation at each state).
  ('BLOCKED','CANCELLED',false,false),
  ('RUNNING','BLOCKED',false,true),    ('BLOCKED','QUEUED',false,false),
  ('QUEUED','BLOCKED',false,true),     ('PLANNED','BLOCKED',false,true),
  ('RUNNING','FAILED',true,false),     ('VERIFYING','FAILED',true,false),
  ('CREATED','FAILED',false,false),
  ('RUNNING','QUARANTINED',true,false),('VERIFYING','QUARANTINED',true,false),
  ('QUEUED','QUARANTINED',true,false);
