# Task-State Authority Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single fenced writer that owns every task-state transition in the OpenAlice command center, so a stale lease holder cannot write and no state exists that isn't declared.

**Architecture:** One FastAPI process over one Postgres database. All transitions funnel through a PL/pgSQL function whose guards (fencing token + declared state edge + verified-slot check) sit *inside* the statement, and that writes the audit row and outbox event in the same transaction. Python is a thin caller; the database is the arbiter.

**Tech Stack:** Python 3.13 (pinned via `uv`), asyncpg, PL/pgSQL, pytest + pytest-asyncio, Postgres 15 (Docker Compose for tests, Homebrew for dev), FastAPI. No Redis, no ORM.

**Spec:** `docs/superpowers/specs/2026-10-31-openalice-task-engine-design.md` @ `ac8752d`. The spec argues from measured evidence (§3) — read it before implementing. This plan covers spec §6, §7, §10, §12, §13, §16 and tasks §17.1–17.4, 17.7–17.9, 17.11–17.12.

**Plan 1 of 3.** Plan 2 = worktree pool + merge-back (§9) and §17.5. Plan 3 = adapters + the three dashboard pages (§11, §14) and a full process-kill restart test. Nothing in this plan touches a git worktree, the HUD, launchd, or trading.

---

## Global Constraints

Every task below satisfies these. Values are verbatim from the spec.

- Python is pinned to **3.13** via `.python-version`; system 3.14.5 is not used (spec §18: `pydantic-core` wheels are thin on 3.14).
- Dependencies installed with **`uv sync`** only. No `pip install` into system Python, no global installs.
- Tests run against **real Postgres 15**, never SQLite (spec §17: SQLite can't exercise `SKIP LOCKED` or row locks).
- **Redis is not a dependency.** It must not appear in `pyproject.toml`, `docker-compose.yml`, or any import (spec §18).
- **Mock provider only. No network call that spends money.** No `OPENAI_*` credential exists; DoD #3 stays BLOCKED (spec §12).
- No secret, API key, or token value may reach a log line, an `audit_events` row, a commit message, or test output (spec §12, §16).
- Trading is **PAPER-only**; no order path, no trading credential, no live endpoint anywhere in this repo (spec §1.1).
- **No writes outside `/Users/aryanagarwal/openalice-command-center`.** Never touch `~/openalice-fleet` (10 commits ahead of `origin/main`, three untracked items being preserved), `~/openalice-ui`, `~/openalice-universal-command-center` (3-file stub, left as found), `~/fleet-worktrees/*`, the HUD on `:4747`, or any launchd service (spec §21).
- **No remote is configured and none is created.** All commits stay local (spec §19 item 4).
- The API binds **loopback only** (`127.0.0.1`). No public interface (spec §16).
- Run everything from the repo root with `PYTHONPATH=src` implicit via pytest's `pythonpath`; the project is a **virtual** uv project and is never packaged or installed.
- Commit after every task. Name the files — never `git add -A`.

### Three documented deviations from the spec text

1. **Spec §5 invariant 1** says `tasks.state` is `CHECK`-constrained to the set present in `state_edges`. Postgres `CHECK` expressions cannot contain subqueries, so no `CHECK` can express it. Task 2 enforces the identical invariant with a `BEFORE`-row trigger that rejects any state absent from `state_edges`, and tests it by inserting an illegal state. The invariant is real; the mechanism differs.
2. **Spec §7** says fencing tokens come from "a per-task sequence". Ten thousand Postgres sequences is an operational liability for no added guarantee. Task 4 uses one global sequence; global monotonicity implies per-task monotonicity, which is the property §7 relies on. Task 4 asserts per-task monotonicity directly.
3. **Spec §5** implies the append-only audit guarantee is enforced by constraint. Task 2 creates a `NOLOGIN` application role and revokes `UPDATE`/`DELETE`/`TRUNCATE` from it, then proves the revocation bites via `SET ROLE`. Tests connect as the superuser (they must be able to `DROP SCHEMA`), so the revocation is demonstrated rather than assumed.

---

## Locked Interfaces

Later tasks import these exact names and types. Do not rename.

```python
# src/authority/transitions.py
@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    reason: str            # "OK" | "NOT_FOUND" | "BAD_TOKEN" | "ILLEGAL_EDGE"
                           # | "SLOT_NOT_VERIFIED" | "EVIDENCE_REQUIRED"
    new_state: str | None

async def task_transition(conn, task_id: int, to_state: str, fencing_token: int,
                          evidence: dict | None, actor: str) -> TransitionResult

# src/authority/fencing.py
async def bump_token(conn, task_id: int) -> int

# src/authority/leases.py
@dataclass(frozen=True)
class Lease:
    task_id: int
    slot_id: str
    fencing_token: int
    expires_at: datetime

async def claim_lease(conn, slot_id: str, task_id: int, ttl_seconds: int) -> Lease | None
async def reap_expired(conn, now: datetime) -> list[int]        # task ids reaped
async def release_lease(conn, task_id: int, reason: str) -> None

# src/authority/outbox.py
async def drain_outbox(conn, publisher, limit: int = 100) -> int
class RecordingPublisher:            # .events: list[dict]

# src/authority/redaction.py
async def redact_jsonb(conn, value: dict) -> dict

# src/authority/provider.py
class PlanError(Exception): ...
@dataclass(frozen=True)
class Plan:
    objective: str
    tasks: list[dict]
class ReasoningAdapter(Protocol):
    async def plan(self, prompt: str, context: dict) -> Plan
class MockProvider:
    def __init__(self, seed: int = 0) -> None: ...
    async def plan(self, prompt: str, context: dict) -> Plan

# src/authority/db.py
async def open_pool(dsn: str | None = None) -> asyncpg.Pool

# src/authority/config.py
@dataclass(frozen=True)
class Config:
    database_url: str
    api_token: str
    bind_host: str
    bind_port: int
    lease_ttl_seconds: int
def load_config() -> Config

# src/authority/api.py
FORBIDDEN_ROUTE_PATTERN: str
def build_app(config: Config, pool) -> FastAPI
def create_app(config: Config, pool) -> FastAPI
```

Schema names locked by Task 2: tables `prompts`, `roles`, `worker_slots`, `tasks`, `state_edges`, `leases`, `outbox_events`, `audit_events`, `worktrees`, `merge_queue`; functions `task_transition(bigint,text,bigint,jsonb,text)`, `audit_reject(...)`, `redact(jsonb)`, `reject_undocumented_state()`; role `authority_app`.

---

### Task 1: Project skeleton and Postgres test harness

The deliverable is a test run proving a real database is reachable and migrations apply. Nothing later can be tested until this exists.

**Files:**
- Create: `pyproject.toml`, `.python-version`, `docker-compose.yml`, `.env.example`, `.gitignore`, `src/authority/__init__.py`, `src/authority/db.py`, `src/authority/config.py`, `src/authority/migrations/.gitkeep`, `tests/conftest.py`, `tests/test_harness.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `open_pool(dsn) -> asyncpg.Pool`, `load_config() -> Config`, and the `pool` / `conn` fixtures every later task uses.

- [ ] **Step 1: Pin Python and declare dependencies**

```bash
echo '3.13' > .python-version
```

`pyproject.toml` — `package = false` keeps this a virtual project, so `uv sync` never needs a build backend:

```toml
[project]
name = "openalice-command-center"
version = "0.1.0"
requires-python = "==3.13.*"
dependencies = ["asyncpg>=0.30", "fastapi>=0.115", "uvicorn>=0.34", "pydantic>=2.10"]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "httpx>=0.28"]

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Install and verify the interpreter is not 3.14**

```bash
uv sync && uv run python -c "import sys;print(sys.version_info[:2])"
```
Expected: `(3, 13)`. If it prints `(3, 14)` stop immediately — the pin failed and the premise of spec §18 is broken.

- [ ] **Step 3: Test database container and env shape**

`docker-compose.yml` — port 55432 so it can never collide with the live HUD or fleet services:

```yaml
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: ciiamlocalonly
      POSTGRES_DB: authority_test
    ports: ["127.0.0.1:55432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d authority_test"]
      interval: 2s
```

`.env.example` documents the shape with an obviously fake value — never a real key:

```
DATABASE_URL=postgresql://postgres:ciiamlocalonly@127.0.0.1:55432/authority_test
AUTHORITY_API_TOKEN=replace-with-a-local-only-secret
LEASE_TTL_SECONDS=90
AUTHORITY_BIND_HOST=127.0.0.1
AUTHORITY_BIND_PORT=4810
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
*.bak
```

- [ ] **Step 4: Write the failing tests**

`tests/test_harness.py`:

```python
async def test_pool_connects_and_schema_is_empty(conn):
    rows = await conn.fetch("select tablename from pg_tables where schemaname='public'")
    assert [r["tablename"] for r in rows] == []

async def test_config_rejects_a_non_loopback_bind(monkeypatch):
    from authority.config import load_config
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/authority_test")
    monkeypatch.setenv("AUTHORITY_API_TOKEN", "t")
    monkeypatch.setenv("AUTHORITY_BIND_HOST", "0.0.0.0")
    try:
        load_config()
    except ValueError as e:
        assert "loopback" in str(e)
    else:
        raise AssertionError("0.0.0.0 bind accepted; spec §16 forbids it")

async def test_config_requires_an_api_token(monkeypatch):
    from authority.config import load_config
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/authority_test")
    monkeypatch.delenv("AUTHORITY_API_TOKEN", raising=False)
    try:
        load_config()
    except ValueError as e:
        assert "AUTHORITY_API_TOKEN" in str(e)
    else:
        raise AssertionError("started with no auth token")
```

- [ ] **Step 5: Run them to verify they fail**

```bash
docker compose up -d db && uv run pytest tests/test_harness.py -v
```
Expected: FAIL with `ModuleNotFoundError: authority.config` — or a connection error if the container isn't healthy yet.

- [ ] **Step 6: Implement `db.py` and `config.py`**

`src/authority/db.py`:

```python
import os
import asyncpg

async def open_pool(dsn: str | None = None) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn or os.environ["DATABASE_URL"], min_size=1, max_size=25
    )
```

`src/authority/config.py`:

```python
import os
from dataclasses import dataclass

_LOOPBACK_OK = ("127.0.0.1", "::1", "localhost")

@dataclass(frozen=True)
class Config:
    database_url: str
    api_token: str
    bind_host: str
    bind_port: int
    lease_ttl_seconds: int

def load_config() -> Config:
    host = os.environ.get("AUTHORITY_BIND_HOST", "127.0.0.1")
    if host not in _LOOPBACK_OK:
        raise ValueError(f"bind host must be loopback, got {host!r}")
    token = os.environ.get("AUTHORITY_API_TOKEN", "")
    if not token:
        raise ValueError("AUTHORITY_API_TOKEN is required")
    return Config(
        database_url=os.environ["DATABASE_URL"],
        api_token=token,
        bind_host=host,
        bind_port=int(os.environ.get("AUTHORITY_BIND_PORT", "4810")),
        lease_ttl_seconds=int(os.environ.get("LEASE_TTL_SECONDS", "90")),
    )
```

`src/authority/__init__.py` stays empty; create `src/authority/migrations/.gitkeep`.

- [ ] **Step 7: Write the fixtures**

`tests/conftest.py` — each test gets a freshly migrated, empty schema. The DSN defaults to the local compose container so a missing `.env` is an obvious connection error rather than a confusing `KeyError`:

```python
import pathlib
import pytest
from authority.db import open_pool

MIG_DIR = pathlib.Path(__file__).parent.parent / "src" / "authority" / "migrations"
DEFAULT_DSN = "postgresql://postgres:ciiamlocalonly@127.0.0.1:55432/authority_test"

async def _migrate(conn):
    await conn.execute("drop schema if exists public cascade; create schema public;")
    for f in sorted(MIG_DIR.glob("*.sql")):
        await conn.execute(f.read_text())

@pytest.fixture
async def pool():
    import os
    p = await open_pool(os.environ.get("DATABASE_URL", DEFAULT_DSN))
    async with p.acquire() as conn:
        await _migrate(conn)
    yield p
    await p.close()

@pytest.fixture
async def conn(pool):
    async with pool.acquire() as c:
        yield c
```

Task 7's restart test opens a second pool with no argument, so export the same default there:

```bash
echo 'export DATABASE_URL="postgresql://postgres:ciiamlocalonly@127.0.0.1:55432/authority_test"' >> .env
```
and `open_pool()` already falls back to `os.environ["DATABASE_URL"]`. If `.env` isn't loaded by the runner, set `DATABASE_URL` inline for that one command; Task 7 spells it out.

- [ ] **Step 8: Run tests to verify they pass**

```bash
uv run pytest tests/test_harness.py -v
```
Expected: 3 passed. The empty-schema assertion also proves the fixture really rebuilt the schema — but note it would also pass if migrations were missing entirely, which is why Task 2's first act is to make it fail.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .python-version docker-compose.yml .env.example .gitignore \
        src/authority/__init__.py src/authority/db.py src/authority/config.py \
        src/authority/migrations/.gitkeep tests/conftest.py tests/test_harness.py
git commit -m "chore: python 3.13 pin, loopback-only config, live postgres harness"
```

---

### Task 2: Schema, declared state edges, the state trigger, and a revoked-write audit role

**Files:**
- Create: `src/authority/migrations/0001_schema.sql`, `tests/test_schema.py`

**Interfaces:**
- Consumes: `conn`, `pool` fixtures.
- Produces: the tables in Locked Interfaces, `redact(jsonb)`, `reject_undocumented_state()`, seed `state_edges`, role `authority_app`.

- [ ] **Step 1: Write the failing tests**

`tests/test_schema.py`:

```python
import asyncpg

LEGAL_STATES = {"CREATED", "PLANNED", "APPROVED", "QUEUED", "RUNNING",
                "VERIFYING", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED",
                "QUARANTINED"}

async def _seed_heads(conn):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")

async def test_every_lifecycle_state_is_declared(conn):
    rows = await conn.fetch(
        "select from_state s from state_edges union select to_state s from state_edges")
    assert {r["s"] for r in rows} == LEGAL_STATES

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
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_schema.py -v
```
Expected: FAIL — `relation "state_edges" does not exist`.

- [ ] **Step 3: Write the schema**

`src/authority/migrations/0001_schema.sql`. Note `redact()` is built from `regexp_replace` on *text* — Postgres has no `jsonb_regexp_replace`, so the jsonb is cast through text and back.

```sql
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
create or replace function redact(p jsonb) returns jsonb as $$
  select regexp_replace(
           regexp_replace(p::text,
             '(nvapi|sk|ghp|gho|github_pat)[A-Za-z0-9_\-]{8,}', '<redacted>', 'g'),
           '(?i)(bearer +)[A-Za-z0-9._\-]+', '\1<redacted>', 'g'
         )::jsonb
$$ language sql;

-- Deviation 3: append-only proven by a real non-superuser role.
create role authority_app nocreate nosuperuser nologin;
grant usage on schema public to authority_app;
grant select, insert on tasks, prompts, roles, worker_slots, state_edges,
                       leases, outbox_events, audit_events, worktrees, merge_queue
  to authority_app;
grant usage, select on all sequences in schema public to authority_app;
revoke update, delete, truncate on audit_events from authority_app;
revoke update, delete, truncate on outbox_events from authority_app;

insert into state_edges(from_state,to_state,requires_evidence,retryable) values
  ('CREATED','PLANNED',false,false),   ('PLANNED','APPROVED',false,false),
  ('APPROVED','QUEUED',false,false),   ('QUEUED','RUNNING',false,false),
  ('RUNNING','VERIFYING',true,false),  ('VERIFYING','COMPLETED',true,false),
  ('CREATED','CANCELLED',false,false), ('PLANNED','CANCELLED',false,false),
  ('APPROVED','CANCELLED',false,false),('QUEUED','CANCELLED',false,false),
  ('RUNNING','CANCELLED',false,false), ('VERIFYING','CANCELLED',false,false),
  ('RUNNING','BLOCKED',false,true),    ('BLOCKED','QUEUED',false,false),
  ('QUEUED','BLOCKED',false,true),     ('PLANNED','BLOCKED',false,true),
  ('RUNNING','FAILED',true,false),     ('VERIFYING','FAILED',true,false),
  ('CREATED','FAILED',false,false),
  ('RUNNING','QUARANTINED',true,false),('VERIFYING','QUARANTINED',true,false),
  ('QUEUED','QUARANTINED',true,false);
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_schema.py -v
```
Expected: 6 passed. `set role` inside the fixture's connection only affects that session; the `conn` fixture re-acquires per test, and `_migrate` drops the schema between tests, so no privilege leak crosses tests. If `test_audit_events_cannot_be_updated_by_the_app_role` errors with `role "authority_app" does not exist`, the migration order is wrong — `sorted(MIG_DIR.glob("*.sql"))` must apply `0001` in full before tests run.

- [ ] **Step 5: Commit**

```bash
git add src/authority/migrations/0001_schema.sql tests/test_schema.py
git commit -m "feat: schema, declared state edges, trigger-enforced vocabulary, append-only role"
```

---

### Task 3: `task_transition()` — the sole writer

**Files:**
- Create: `src/authority/migrations/0002_transition.sql`, `src/authority/transitions.py`, `tests/test_transitions.py`

**Interfaces:**
- Consumes: `state_edges`, `tasks`, `worker_slots`, `audit_events`, `outbox_events`, `redact()`.
- Produces: SQL `task_transition(bigint,text,bigint,jsonb,text) returns table(ok boolean, reason text, new_state text)` and the Python wrapper in Locked Interfaces.

- [ ] **Step 1: Write the failing tests**

`tests/test_transitions.py`:

```python
from authority.transitions import task_transition

async def seed(conn, state="CREATED", token=0, slot=None, verified=True):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
    if slot:
        await conn.execute(
            "insert into worker_slots(id,adapter,verified_at) values($1,'qoder',now())", slot)
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
    tid = await seed(conn, state="APPROVED", slot="s-mock")
    await conn.execute(
        "insert into worker_slots(id,adapter,verified_at) values('s-mock','mock',now())")
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert (res.ok, res.reason) == (False, "SLOT_NOT_VERIFIED")

async def test_queued_rejects_an_unverified_real_slot(conn):
    tid = await seed(conn, state="APPROVED", slot="s-raw")
    await conn.execute("insert into worker_slots(id,adapter) values('s-raw','qoder')")
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert (res.ok, res.reason) == (False, "SLOT_NOT_VERIFIED")

async def test_queued_accepts_a_verified_real_slot(conn):
    tid = await seed(conn, state="APPROVED", slot="s-ok")
    res = await task_transition(conn, tid, "QUEUED", 0, None, "sched")
    assert res.ok is True
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_transitions.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.transitions`.

- [ ] **Step 3: Write the SQL function**

`src/authority/migrations/0002_transition.sql`. Guards are checked in explicit order so every rejection returns a distinct reason; `for update` serializes per task, which is what makes Task 5's race resolve to one winner.

```sql
create or replace function audit_reject(
  p_actor text, p_action text, p_target text, p_before text, p_reason text, p_token bigint
) returns void as $$
  insert into audit_events(actor,action,target,before_state,after_state,fencing_token,outcome)
  values (p_actor,p_action,p_target,p_before,null,p_token,p_reason);
$$ language sql;

create or replace function task_transition(
  p_task_id bigint, p_to_state text, p_token bigint, p_evidence jsonb, p_actor text
) returns table(ok boolean, reason text, new_state text) as $$
declare
  v_state text; v_token bigint; v_slot text; v_found boolean;
begin
  select t.state, t.fencing_token, t.assigned_slot_id into v_state, v_token, v_slot
    from tasks t where t.id = p_task_id
      for update;
  v_found := found;
  if not v_found then
    return query select false, 'NOT_FOUND', null::text;
  end if;

  if v_token <> p_token then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'BAD_TOKEN',p_token);
    return query select false, 'BAD_TOKEN', v_state;
  end if;

  if not exists (select 1 from state_edges e
                  where e.from_state = v_state and e.to_state = p_to_state) then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,'ILLEGAL_EDGE',p_token);
    return query select false, 'ILLEGAL_EDGE', v_state;
  end if;

  if (select e.requires_evidence from state_edges e
       where e.from_state = v_state and e.to_state = p_to_state)
     and p_evidence is null then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,
                         'EVIDENCE_REQUIRED',p_token);
    return query select false, 'EVIDENCE_REQUIRED', v_state;
  end if;

  if p_to_state = 'QUEUED' and not exists (
       select 1 from worker_slots s
        where s.id = v_slot and s.verified_at is not null and s.adapter <> 'mock') then
    perform audit_reject(p_actor,'transition',p_task_id::text,v_state,
                         'SLOT_NOT_VERIFIED',p_token);
    return query select false, 'SLOT_NOT_VERIFIED', v_state;
  end if;

  update tasks set state = p_to_state, updated_at = now(),
                   completed_at = case when p_to_state in ('COMPLETED','FAILED',
                       'CANCELLED','QUARANTINED') then now() else completed_at end
    where id = p_task_id;

  insert into audit_events(actor,action,target,before_state,after_state,fencing_token,
                           redacted_payload,outcome)
    values (p_actor,'transition',p_task_id::text,v_state,p_to_state,p_token,
            redact(coalesce(p_evidence,'{}'::jsonb)),'OK');

  insert into outbox_events(prompt_id,task_id,event_type,payload,dedupe_key)
    select t.prompt_id, p_task_id, 'task.'||p_to_state,
           jsonb_build_object('from',v_state,'to',p_to_state,'token',p_token),
           p_task_id||':'||p_to_state||':'||p_token
      from tasks t where t.id = p_task_id;

  return query select true, 'OK', p_to_state;
end $$ language plpgsql;
```

- [ ] **Step 4: Write the Python wrapper**

`src/authority/transitions.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_transitions.py -v
```
Expected: 7 passed. `test_illegal_edge_is_rejected_and_state_untouched` also asserts the rejection produced an audit row — silence is how the four blocked registries on 2026-10-31 looked healthy.

- [ ] **Step 6: Commit**

```bash
git add src/authority/migrations/0002_transition.sql src/authority/transitions.py tests/test_transitions.py
git commit -m "feat: task_transition as the sole state writer with per-task row locking"
```

---

### Task 4: Fencing tokens

**Files:**
- Create: `src/authority/fencing.py`, `src/authority/migrations/0003_fencing.sql`, `tests/test_fencing.py`

**Interfaces:**
- Consumes: `tasks.fencing_token`, `task_transition`.
- Produces: `bump_token(conn, task_id) -> int`, SQL `next_fencing_token() returns bigint`.

- [ ] **Step 1: Write the failing tests**

`tests/test_fencing.py`:

```python
from authority.fencing import bump_token
from authority.transitions import task_transition

async def seed(conn):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
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
    a, b = await seed(conn), await seed(conn)
    ta = await bump_token(conn, a)
    tb = await bump_token(conn, b)
    assert ta != tb
    assert await task_transition(conn, b, "PLANNED", ta, None, "crossed").ok is False

async def test_bump_on_a_missing_task_returns_none(conn):
    assert await bump_token(conn, 123456) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_fencing.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.fencing`.

- [ ] **Step 3: Implement**

`src/authority/migrations/0003_fencing.sql` — deviation 2, one global sequence instead of 10K:

```sql
create sequence fencing_token_seq;

create or replace function next_fencing_token() returns bigint as
  $$ select nextval('fencing_token_seq') $$ language sql;
```

`src/authority/fencing.py`:

```python
async def bump_token(conn, task_id: int) -> int | None:
    return await conn.fetchval(
        "update tasks set fencing_token = next_fencing_token(), updated_at = now() "
        "where id = $1 returning fencing_token", task_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_fencing.py -v
```
Expected: 5 passed. Note `nextval` is called even by the `update` that matches zero rows, so tokens are never reused across tasks — `test_tokens_never_reused_across_tasks` pins that.

- [ ] **Step 5: Commit**

```bash
git add src/authority/migrations/0003_fencing.sql src/authority/fencing.py tests/test_fencing.py
git commit -m "feat: monotonic fencing tokens that fence a stale lease holder"
```

---

### Task 5: The two-writer race — the engine's central claim

**Files:**
- Create: `tests/test_race.py`

**Interfaces:** Consumes everything above. Produces the evidence spec §17.1 demands.

- [ ] **Step 1: Write the race test**

`tests/test_race.py`. Twenty separate pooled connections, none sharing a transaction — the point is that the row lock, not application order, is the arbiter:

```python
import asyncio
from authority.transitions import task_transition

async def test_exactly_one_of_twenty_concurrent_transitions_wins(pool):
    async with pool.acquire() as c:
        await c.execute("insert into prompts(id) values('p1')")
        await c.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
        tid = await c.fetchval(
            "insert into tasks(prompt_id,role_id,objective) values('p1','r1','o') returning id")

    barrier = asyncio.Event()

    async def attempt(i: int) -> bool:
        await barrier.wait()                     # align all twenty on the same row
        async with pool.acquire() as c:
            async with c.transaction():
                return (await task_transition(c, tid, "PLANNED", 0, None, f"writer-{i}")).ok

    racers = [asyncio.ensure_future(attempt(i)) for i in range(20)]
    barrier.set()
    results = await asyncio.gather(*racers)

    assert sum(results) == 1, f"{sum(results)} writers succeeded — sole-writer is a fiction"

    async with pool.acquire() as c:
        assert await c.fetchval("select state from tasks where id=$1", tid) == "PLANNED"
        assert await c.fetchval(
            "select count(*) from outbox_events where task_id=$1 and event_type='task.PLANNED'"
        ) == 1
        assert await c.fetchval("select count(*) from audit_events where outcome='OK'") == 1
        assert await c.fetchval("select count(*) from audit_events") == 20

async def test_a_reaped_holder_cannot_resume(pool):
    from authority.fencing import bump_token
    async with pool.acquire() as c:
        await c.execute("insert into prompts(id) values('p1')")
        await c.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
        tid = await c.fetchval(
            "insert into tasks(prompt_id,role_id,objective,state) "
            "values('p1','r1','o','RUNNING') returning id")
        old = await c.fetchval("select fencing_token from tasks where id=$1", tid)
        new = await bump_token(c, tid)               # reaper bumped it
        assert new != old
        assert (await task_transition(c, tid, "VERIFYING", old, {"x": 1}, "ghost")).ok is False
```

The barrier exists so all twenty coroutines reach `task_transition` before any of them has been scheduled past it — without it, asyncio may run them strictly one at a time and the test would prove nothing about contention.

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/test_race.py -v
```
Expected: 2 passed.

- [ ] **Step 3: Prove the race test can fail, then restore**

A race test that passes on the first try may simply be lucky. Remove the lock and confirm it goes red:

```bash
cp src/authority/migrations/0002_transition.sql /tmp/0002.keep
perl -0pi -e 's/\n\s*for update;/;/' src/authority/migrations/0002_transition.sql
grep -c 'for update;' src/authority/migrations/0002_transition.sql   # expect 0
uv run pytest tests/test_race.py -v
cp /tmp/0002.keep src/authority/migrations/0002_transition.sql
grep -c 'for update;' src/authority/migrations/0002_transition.sql   # expect 1
uv run pytest tests/test_race.py -v
```
Expected: mutated → **FAIL** (some `sum(results) != 1`, or `audit_events != 20`, or a double outbox row). Restored → 2 passed. If the mutated run still passes, the test is decoration: raise the writer count and add `asyncio.sleep(0)` inside `attempt` before the acquire so the coroutines genuinely interleave, then re-prove. Do not commit until the mutant is killed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_race.py
git commit -m "test: 20-writer race proves exactly one transition wins"
```
Record the mutant observation in the commit body: `without for-update: <what happened>; restored: pass`.

---

### Task 6: Leases, TTL reaping, and cancellation

**Files:**
- Create: `src/authority/leases.py`, `src/authority/migrations/0004_lease_claim.sql`, `tests/test_leases.py`

**Interfaces:**
- Consumes: `next_fencing_token()`, `state_edges.retryable`, `tasks`, `leases`.
- Produces: `claim_lease`, `reap_expired`, `release_lease`.

`reap_expired` takes its clock as a **parameter**. That is the seam: TTL behaviour is tested by passing a future timestamp, never by sleeping or by spoofing the database clock.

- [ ] **Step 1: Write the failing tests**

`tests/test_leases.py`:

```python
from datetime import datetime, timedelta, timezone
from authority.leases import claim_lease, reap_expired, release_lease
from authority.transitions import task_transition

def later(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)

async def seed(conn, state="APPROVED", slot="s1"):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
    await conn.execute(
        "insert into worker_slots(id,adapter,verified_at) values($1,'qoder',now())", slot)
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective,state,assigned_slot_id) "
        "values('p1','r1','o',$1,$2) returning id", state, slot)

async def test_claim_moves_approved_to_running_and_returns_a_lease(conn):
    tid = await seed(conn)
    lease = await claim_lease(conn, "s1", tid, 90)
    assert lease is not None and lease.task_id == tid
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "RUNNING"
    assert lease.fencing_token != 0

async def test_the_granted_token_writes_and_the_old_one_does_not(conn):
    tid = await seed(conn)
    lease = await claim_lease(conn, "s1", tid, 90)
    stale = await task_transition(conn, tid, "VERIFYING", 0, {"x": 1}, "zombie")
    assert (stale.ok, stale.reason) == (False, "BAD_TOKEN")
    fresh = await task_transition(conn, tid, "VERIFYING", lease.fencing_token,
                                 {"x": 1}, "holder")
    assert fresh.ok is True

async def test_a_second_claim_of_a_held_task_returns_none(conn):
    tid = await seed(conn)
    assert await claim_lease(conn, "s1", tid, 90) is not None
    assert await claim_lease(conn, "s2", tid, 90) is None

async def test_claim_outside_approved_is_refused(conn):
    tid = await seed(conn, state="CREATED")
    assert await claim_lease(conn, "s1", tid, 90) is None
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"

async def test_expired_lease_on_a_retryable_edge_is_blocked_then_requeued(conn):
    tid = await seed(conn)
    await claim_lease(conn, "s1", tid, 1)
    assert await reap_expired(conn, now=later(5)) == [tid]
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "BLOCKED"
    tok = await conn.fetchval("select fencing_token from tasks where id=$1", tid)
    assert (await task_transition(conn, tid, "QUEUED", tok, None, "sched")).ok is True

async def test_reaper_ignores_an_unexpired_lease(conn):
    tid = await seed(conn)
    await claim_lease(conn, "s1", tid, 3600)
    assert await reap_expired(conn, now=later(5)) == []

async def test_reaper_skips_a_released_lease(conn):
    tid = await seed(conn)
    await claim_lease(conn, "s1", tid, 1)
    await release_lease(conn, tid, "done")
    assert await reap_expired(conn, now=later(5)) == []

async def test_cancellation_revokes_the_lease_and_late_results_are_inert(conn):
    tid = await seed(conn)
    lease = await claim_lease(conn, "s1", tid, 90)
    tok = await conn.fetchval("select fencing_token from tasks where id=$1", tid)
    assert (await task_transition(conn, tid, "CANCELLED", tok, None, "user")).ok is True
    assert await conn.fetchval("select count(*) from leases where task_id=$1 "
                               "and released_at is null", tid) == 0
    late = await task_transition(conn, tid, "VERIFYING", lease.fencing_token,
                                 {"x": 1}, "slow-worker")
    assert late.ok is False

async def test_gutting_retryability_routes_the_reaper_to_quarantined(conn):
    tid = await seed(conn)
    await claim_lease(conn, "s1", tid, 1)
    await conn.execute("update state_edges set retryable=false "
                       "where from_state='RUNNING' and to_state='BLOCKED'")
    await conn.execute("insert into state_edges(from_state,to_state,requires_evidence,retryable) "
                       "values('RUNNING','QUARANTINED',false,false)")
    assert await reap_expired(conn, now=later(5)) == [tid]
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "QUARANTINED"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_leases.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.leases`.

- [ ] **Step 3: Write the claim function**

`src/authority/migrations/0004_lease_claim.sql`:

```sql
create or replace function claim_lease(p_task_id bigint, p_slot text, p_ttl int)
returns table(ok boolean, reason text, fencing_token bigint, expires_at timestamptz) as $$
declare v_state text; v_found boolean; tok bigint; exp timestamptz;
begin
  select t.state into v_state from tasks t where t.id = p_task_id for update;
  v_found := found;
  if not v_found then
    return query select false, 'NOT_FOUND', 0::bigint, null::timestamptz;
  end if;

  if v_state <> 'APPROVED' then
    return query select false, 'ILLEGAL_EDGE', 0::bigint, null::timestamptz;
  end if;

  if exists (select 1 from leases l where l.task_id = p_task_id and l.released_at is null) then
    return query select false, 'ALREADY_HELD', 0::bigint, null::timestamptz;
  end if;

  if not exists (select 1 from worker_slots s
                  where s.id = p_slot and s.verified_at is not null and s.adapter <> 'mock') then
    return query select false, 'SLOT_NOT_VERIFIED', 0::bigint, null::timestamptz;
  end if;

  update tasks set fencing_token = next_fencing_token(), state = 'RUNNING',
                   assigned_slot_id = p_slot, updated_at = now()
    where id = p_task_id;
  select t.fencing_token into tok from tasks t where t.id = p_task_id;
  exp := now() + make_interval(secs => p_ttl);

  insert into leases(task_id, slot_id, fencing_token, expires_at)
    values (p_task_id, p_slot, tok, exp);

  insert into audit_events(actor,action,target,before_state,after_state,fencing_token,outcome)
    values (p_slot,'lease_claim',p_task_id::text,v_state,'RUNNING',tok,'OK');

  insert into outbox_events(prompt_id,task_id,event_type,payload,dedupe_key)
    select t.prompt_id, p_task_id, 'task.LEASED',
           jsonb_build_object('slot',p_slot,'token',tok), p_task_id||':leased:'||tok
      from tasks t where t.id = p_task_id;

  return query select true, 'OK', tok, exp;
end $$ language plpgsql;
```

The `APPROVED`-only precondition here is deliberate: the claim *is* the `APPROVED → RUNNING` edge, so there is exactly one code path that can start a task and it cannot be reached from a state where the fleet would be surprised to find work running.

- [ ] **Step 4: Implement the Python side**

`src/authority/leases.py`:

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Lease:
    task_id: int
    slot_id: str
    fencing_token: int
    expires_at: datetime

async def claim_lease(conn, slot_id: str, task_id: int, ttl_seconds: int) -> Lease | None:
    row = await conn.fetchrow("select * from claim_lease($1,$2,$3)",
                              task_id, slot_id, ttl_seconds)
    if not row["ok"]:
        return None
    return Lease(task_id, slot_id, row["fencing_token"], row["expires_at"])

async def release_lease(conn, task_id: int, reason: str) -> None:
    await conn.execute("update leases set released_at = now(), released_reason = $2 "
                       "where task_id = $1 and released_at is null", task_id, reason)

async def _next_target(conn) -> str:
    retryable = await conn.fetchval(
        "select retryable from state_edges "
        "where from_state='RUNNING' and to_state='BLOCKED'")
    return "BLOCKED" if retryable else "QUARANTINED"

async def reap_expired(conn, now: datetime) -> list[int]:
    """Expire held leases and move the task on. `now` is the only time source."""
    rows = await conn.fetch(
        "select l.task_id, l.fencing_token from leases l "
        "  join tasks t on t.id = l.task_id "
        "where l.released_at is null and l.expires_at < $1 and t.state = 'RUNNING' "
        "order by l.task_id", now)
    reaped: list[int] = []
    for r in rows:
        target = await _next_target(conn)
        bumped = await conn.fetchval(
            "update tasks set fencing_token = next_fencing_token(), state = $2, "
            "  updated_at = now() where id = $1 returning fencing_token",
            r["task_id"], target)
        await conn.execute(
            "update leases set released_at = now(), released_reason = 'expired' "
            "where task_id = $1 and released_at is null", r["task_id"])
        await conn.execute(
            "insert into audit_events(actor,action,target,before_state,after_state,"
            "  fencing_token,outcome) "
            "values('reaper','lease_expiry',$1::text,'RUNNING',$2,$3,'OK')",
            r["task_id"], target, bumped)
        reaped.append(r["task_id"])
    return reaped
```

Cancellation revoking the lease is *not* in Python — it belongs in SQL so it cannot be forgotten by a caller. Append to `0004_lease_claim.sql`:

```sql
create or replace function on_cancel_release_lease() returns trigger as $$
begin
  if new.state = 'CANCELLED' then
    update leases set released_at = now(), released_reason = 'cancelled'
      where task_id = new.id and released_at is null;
  end if;
  return new;
end $$ language plpgsql;

create trigger tasks_cancel_releases_lease
  after update of state on tasks
  for each row execute function on_cancel_release_lease();
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_leases.py -v
```
Expected: 9 passed. `test_gutting_retryability_routes_the_reaper_to_quarantined` also proves the reaper reads policy from `state_edges` rather than hardcoding `BLOCKED` — that test is the mutant for §17.12, run inside its own task because it is the only practical way to exercise the non-retryable branch given the seed declares `RUNNING→BLOCKED` as retryable.

- [ ] **Step 6: Commit**

```bash
git add src/authority/migrations/0004_lease_claim.sql src/authority/leases.py tests/test_leases.py
git commit -m "feat: atomic lease claim, TTL reaper honouring retryability, cancel releases lease"
```

---

### Task 7: Outbox drain, exactly-once publication, and restart recovery

**Files:**
- Create: `src/authority/outbox.py`, `tests/test_outbox.py`

**Interfaces:**
- Consumes: `outbox_events` written by `task_transition` and `claim_lease`.
- Produces: `drain_outbox(conn, publisher, limit) -> int`, `RecordingPublisher`.

- [ ] **Step 1: Write the failing tests**

`tests/test_outbox.py`:

```python
import asyncio
from authority.db import open_pool
from authority.outbox import RecordingPublisher, drain_outbox
from authority.transitions import task_transition

async def make_task(conn):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective) values('p1','r1','o') returning id")

async def test_drain_publishes_once_and_marks_published(conn):
    tid = await make_task(conn)
    await task_transition(conn, tid, "PLANNED", 0, None, "t")
    pub = RecordingPublisher()
    assert await drain_outbox(conn, pub) == 1
    assert await drain_outbox(conn, pub) == 0
    assert len(pub.events) == 1
    assert pub.events[0]["event_type"] == "task.PLANNED"

async def test_two_drainers_never_publish_the_same_event(pool):
    async with pool.acquire() as seed_conn:
        tid = await make_task(seed_conn)
        await task_transition(seed_conn, tid, "PLANNED", 0, None, "t")
    a, b = RecordingPublisher(), RecordingPublisher()
    async with pool.acquire() as c1, pool.acquire() as c2:
        ra, rb = await asyncio.gather(drain_outbox(c1, a), drain_outbox(c2, b))
    assert ra + rb == 1, f"double-published: {ra}+{rb}"
    assert len(a.events) + len(b.events) == 1

async def test_unique_dedupe_key_rejects_a_replayed_event(conn):
    await conn.execute("insert into outbox_events(event_type,dedupe_key) values('x','k1')")
    try:
        await conn.execute("insert into outbox_events(event_type,dedupe_key) values('x','k1')")
    except Exception as e:
        assert "unique" in str(e).lower()
    else:
        raise AssertionError("duplicate dedupe_key accepted — exactly-once is unenforced")

async def test_transition_and_outbox_rollback_together(conn):
    tid = await make_task(conn)
    try:
        async with conn.transaction():
            await task_transition(conn, tid, "PLANNED", 0, None, "t")
            raise RuntimeError("simulated crash after the transition wrote its rows")
    except RuntimeError:
        pass
    assert await conn.fetchval("select state from tasks where id=$1", tid) == "CREATED"
    assert await conn.fetchval("select count(*) from outbox_events") == 0, "orphan event"

async def test_a_new_process_sees_unpublished_events_and_drains_them_once(pool):
    """Restart recovery: an event left unpublished by a crash is published exactly once."""
    async with pool.acquire() as c:
        tid = await make_task(c)
        await task_transition(c, tid, "PLANNED", 0, None, "t")

    pub = RecordingPublisher()
    async with pool.acquire() as c:
        assert await drain_outbox(c, pub) == 1

    # "restart": a brand-new pool, exactly as a fresh process would build it.
    import os
    pool2 = await open_pool(os.environ.get("DATABASE_URL", DEFAULT_DSN))
    pub2 = RecordingPublisher()
    async with pool2.acquire() as c:
        assert await drain_outbox(c, pub2) == 0
    await pool2.close()
    assert len(pub.events) == 1 and pub2.events == []
```

`DEFAULT_DSN` is the constant defined in `tests/conftest.py`; import it at the top of the test file:

```python
from conftest import DEFAULT_DSN
```

Run this task's tests with the DSN available, since `open_pool()` with no argument reads the environment:

```bash
DATABASE_URL="postgresql://postgres:ciiamlocalonly@127.0.0.1:55432/authority_test" \
  uv run pytest tests/test_outbox.py -v
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_outbox.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.outbox`.

- [ ] **Step 3: Implement the drain**

`src/authority/outbox.py`:

```python
from typing import Protocol

class Publisher(Protocol):
    async def publish(self, event: dict) -> None:

class RecordingPublisher:
    """Test publisher. Task 10's SSE broadcaster is the production one."""
    def __init__(self) -> None:
        self.events: list[dict] = []
    async def publish(self, event: dict) -> None:
        self.events.append(event)

async def drain_outbox(conn, publisher, limit: int = 100) -> int:
    """Claim unpublished events and publish them. skip locked keeps two drainers apart."""
    rows = await conn.fetch(
        "select id, prompt_id, task_id, event_type, payload, dedupe_key from outbox_events "
        "where published_at is null order by id limit $1 for update skip locked", limit)
    for r in rows:
        await publisher.publish(dict(r))
        await conn.execute("update outbox_events set published_at = now() where id = $1",
                           r["id"])
    return len(rows)
```

Because `select … for update skip locked` holds the row lock for the transaction, the caller must run `drain_outbox` inside a transaction so the claim and the `published_at` mark commit together. Make that explicit rather than trusting the caller — wrap it:

```python
async def drain_outbox(conn, publisher, limit: int = 100) -> int:
    async with conn.transaction():
        rows = await conn.fetch(
            "select id, prompt_id, task_id, event_type, payload, dedupe_key from outbox_events "
            "where published_at is null order by id limit $1 for update skip locked", limit)
        for r in rows:
            await publisher.publish(dict(r))
            await conn.execute("update outbox_events set published_at = now() where id = $1",
                               r["id"])
        return len(rows)
```

Use this second version. If the fixture's connection is already inside a transaction, asyncpg raises — which is correct and loud, not silent.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_outbox.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/authority/outbox.py tests/test_outbox.py tests/conftest.py
git commit -m "feat: transactional outbox drained once, skip-locked, deduped by key"
```

---

### Task 8: Redaction proven against emitted rows, not against intent

**Files:**
- Create: `src/authority/redaction.py`, `tests/test_redaction.py`

**Interfaces:** Consumes SQL `redact(jsonb)`. Produces `redact_jsonb(conn, value) -> dict`.

Task 2 already tests `redact()` directly. This task proves the *path*: a secret fed through a transition must not appear in what the database emits.

- [ ] **Step 1: Write the failing tests**

`tests/test_redaction.py`:

```python
import json
from authority.redaction import redact_jsonb
from authority.transitions import task_transition

SECRETS = {
    "nvidia": "nvapi-AbCdEf1234567890ghiJKLMNOP",
    "openai": "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
    "github": "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "pat": "github_pat_11ABCDEFG0abcdefghijklMN",
    "bearer": "Bearer zzzz-very-secret-token-value",
}

async def seed(conn):
    await conn.execute("insert into prompts(id) values('p1')")
    await conn.execute("insert into roles(id,name,profile_version) values('r1','T',1)")
    return await conn.fetchval(
        "insert into tasks(prompt_id,role_id,objective) values('p1','r1','o') returning id")

async def test_redact_jsonb_removes_every_shape(conn):
    out = json.dumps(await redact_jsonb(conn, dict(SECRETS)))
    for value in SECRETS.values():
        assert value not in out, f"{value[:8]}… survived redaction"
    assert "<redacted>" in out

async def test_a_secret_in_evidence_never_reaches_audit_events(conn):
    tid = await seed(conn)
    await task_transition(conn, tid, "RUNNING", 0, {"log": SECRETS["nvidia"]}, "t")
    blob = " ".join(r["p"] for r in await conn.fetch(
        "select redacted_payload::text p from audit_events"))
    assert SECRETS["nvidia"] not in blob, "secret landed in the audit trail"

async def test_a_secret_never_reaches_the_outbox_payload(conn):
    tid = await seed(conn)
    await task_transition(conn, tid, "PLANNED", 0, {"note": SECRETS["openai"]}, "t")
    blob = " ".join(r["p"] for r in await conn.fetch("select payload::text p from outbox_events"))
    assert SECRETS["openai"] not in blob

async def test_ordinary_evidence_is_preserved_not_mangled(conn):
    tid = await seed(conn)
    await conn.execute("update tasks set state='RUNNING' where id=$1", tid)
    res = await task_transition(conn, tid, "VERIFYING", 0, {"tests_passed": 7}, "t")
    assert res.ok is True
    row = await conn.fetchval(
        "select redacted_payload::text from audit_events where after_state='VERIFYING'")
    assert "7" in row

async def test_redaction_is_not_a_truncation(conn):
    long_value = "SAFE-" + ("x" * 5000)
    out = await redact_jsonb(conn, {"v": long_value})
    assert out["v"].startswith("SAFE-") and len(out["v"]) > 4000, \
        "redaction shortened the payload — that is truncation, not scrubbing"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_redaction.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.redaction`.

- [ ] **Step 3: Implement**

`src/authority/redaction.py`:

```python
import json

async def redact_jsonb(conn, value: dict) -> dict:
    row = await conn.fetchval("select redact($1::jsonb)", json.dumps(value))
    return json.loads(row)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_redaction.py -v
```
Expected: 5 passed. If `test_a_secret_in_evidence_never_reaches_audit_events` fails, fix `redact()` in `0001_schema.sql`. Do **not** weaken the test, and do not add Python-side scrubbing in front of the SQL version — spec §12 requires the emitted artefact to be clean, and `test_redaction_is_not_a_truncation` exists because truncation is the usual fake fix.

- [ ] **Step 5: Commit**

```bash
git add src/authority/redaction.py tests/test_redaction.py src/authority/migrations/0001_schema.sql
git commit -m "test: redaction proven against emitted audit and outbox rows, not just inputs"
```

---

### Task 9: Offline mock reasoning adapter

**Files:**
- Create: `src/authority/provider.py`, `tests/test_provider.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Plan`, `PlanError`, `ReasoningAdapter`, `MockProvider`. Task 10 depends on `MockProvider(seed=0).plan(prompt, context)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_provider.py`:

```python
import pytest
from authority.provider import MockProvider, Plan, PlanError

async def test_plan_is_deterministic_for_a_given_seed():
    a = await MockProvider(seed=1).plan("audit the repo and write tests", {})
    b = await MockProvider(seed=1).plan("audit the repo and write tests", {})
    assert a == b
    assert isinstance(a, Plan)

async def test_every_planned_task_carries_the_fields_task_three_needs():
    plan = await MockProvider(seed=1).plan("do the thing", {})
    assert plan.tasks
    for t in plan.tasks:
        assert {"objective", "role_id", "priority", "acceptance"} <= set(t)
        assert "evidence" in t["acceptance"]

async def test_distinct_prompts_yield_distinct_objectives():
    a = await MockProvider(seed=1).plan("first task", {})
    b = await MockProvider(seed=1).plan("second task", {})
    assert a.tasks[0]["objective"] != b.tasks[0]["objective"]

async def test_empty_prompt_is_rejected_rather_than_invented():
    with pytest.raises(PlanError):
        await MockProvider(seed=1).plan("    ", {})

async def test_the_mock_holds_no_http_client():
    p = MockProvider(seed=1)
    assert not any("client" in a or "http" in a for a in vars(p)), \
        "mock provider gained a network dependency"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_provider.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.provider`.

- [ ] **Step 3: Implement**

`src/authority/provider.py`:

```python
import hashlib
from dataclasses import dataclass
from typing import Protocol

class PlanError(Exception):
    ...

@dataclass(frozen=True)
class Plan:
    objective: str
    tasks: list[dict]

class ReasoningAdapter(Protocol):
    async def plan(self, prompt: str, context: dict) -> Plan: ...

class MockProvider:
    """Offline stand-in that lets the §17 suite run with zero spend.

    This is NOT the reasoning engine. Spec §12: no OpenAI credential exists on
    either host, so DoD #3 stays BLOCKED. Swapping in a real adapter requires an
    owner decision about provider policy and money — see spec §19 item 1.
    """

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    async def plan(self, prompt: str, context: dict) -> Plan:
        text = prompt.strip()
        if not text:
            raise PlanError("empty prompt")
        digest = hashlib.sha256(f"{self.seed}:{text}".encode()).hexdigest()[:8]
        return Plan(
            objective=text,
            tasks=[{
                "objective": f"step-1-{digest}",
                "role_id": "r-plan",
                "priority": 5,
                "acceptance": {"evidence": "diff", "must_pass": True},
            }],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_provider.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/authority/provider.py tests/test_provider.py
git commit -m "feat: offline deterministic mock planner; OpenAI path stays blocked on a credential"
```

---

### Task 10: HTTP surface — bearer gate, prompt intake, trace, and provably absent C/D/E routes

**Files:**
- Create: `src/authority/api.py`, `src/authority/__main__.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `Config`, `load_config`, `open_pool`, `task_transition`, `drain_outbox`, `MockProvider`, `PlanError`.
- Produces: `build_app(config, pool) -> FastAPI`, `create_app(config, pool) -> FastAPI`, `FORBIDDEN_ROUTE_PATTERN: str`, routes `POST /prompts`, `GET /prompts/{prompt_id}/trace`, `GET /tasks/{task_id}`, `POST /tasks/{task_id}/transition`, `GET /healthz`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`. Async test functions throughout, because the `pool` fixture is async and `asyncio_mode=auto` resolves async fixtures only for async tests.

```python
import json, re
import pytest
from fastapi.testclient import TestClient
from authority.api import FORBIDDEN_ROUTE_PATTERN, build_app
from authority.config import Config

CFG = Config(database_url="unused-in-tests", api_token="tok-local-test-value",
             bind_host="127.0.0.1", bind_port=4810, lease_ttl_seconds=90)
AUTH = {"authorization": "Bearer tok-local-test-value"}
FRAMEWORK_DEFAULTS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

@pytest.fixture
def client(pool):
    with TestClient(build_app(CFG, pool)) as c:
        yield c

def test_unauthenticated_request_is_rejected(client):
    assert client.post("/prompts", json={"prompt": "do a thing"}).status_code == 401

def test_wrong_token_is_rejected(client):
    r = client.post("/prompts", json={"prompt": "x"},
                    headers={"authorization": "Bearer nope"})
    assert r.status_code == 401

def test_healthz_is_open_and_honest_about_providers(client):
    body = client.get("/healthz").json()
    assert body["provider"] == "mock"
    assert body["openai"] == "unconfigured"

def test_prompt_creates_a_traceable_chain(client):
    r = client.post("/prompts", json={"prompt": "audit the repo"}, headers=AUTH)
    assert r.status_code == 201
    pid = r.json()["prompt_id"]
    assert len(r.json()["task_ids"]) >= 1

    trace = client.get(f"/prompts/{pid}/trace", headers=AUTH)
    assert trace.status_code == 200
    t = trace.json()
    assert t["prompt_id"] == pid
    assert len(t["tasks"]) >= 1
    assert t["audit"], "trace has no audit trail"
    assert t["events"], "trace has no outbox events"

def test_transition_reports_reason_codes_over_http(client):
    pid = client.post("/prompts", json={"prompt": "p"}, headers=AUTH).json()["prompt_id"]
    tid = client.get(f"/prompts/{pid}/trace", headers=AUTH).json()["tasks"][0]["id"]
    ok = client.post(f"/tasks/{tid}/transition",
                     json={"to_state": "PLANNED", "fencing_token": 0, "actor": "me"},
                     headers=AUTH).json()
    assert ok == {"ok": True, "reason": "OK", "new_state": "PLANNED"}
    bad = client.post(f"/tasks/{tid}/transition",
                      json={"to_state": "COMPLETED", "fencing_token": 0, "actor": "me"},
                      headers=AUTH).json()
    assert bad["ok"] is False and bad["reason"] == "ILLEGAL_EDGE"

def test_the_api_token_never_appears_in_a_response_body(client):
    r = client.post("/prompts", json={"prompt": "x"}, headers=AUTH)
    assert CFG.api_token not in r.text
    assert CFG.api_token not in client.get(f"/prompts/{r.json()['prompt_id']}/trace",
                                           headers=AUTH).text

def test_no_declared_route_reaches_trading_hud_launchd_or_git_publish(client):
    """Spec §13: classes C/D/E are absent at the router, not merely unused."""
    declared = {r.path for r in client.app.routes
                if getattr(r, "methods", None) and r.path not in FRAMEWORK_DEFAULTS}
    assert declared, "route scan was vacuous — zero declared routes"
    pattern = re.compile(FORBIDDEN_ROUTE_PATTERN, re.I)
    leaked = sorted(p for p in declared if pattern.search(p))
    assert leaked == [], f"forbidden routes exist: {leaked}"
    assert "/prompts" in declared

def test_empty_prompt_is_refused_not_hallucinated(client):
    assert client.post("/prompts", json={"prompt": "  "}, headers=AUTH).status_code == 422

def test_oversized_path_like_input_is_not_interpreted(client):
    r = client.post("/prompts", json={"prompt": "$c:tests/x" * 40000}, headers=AUTH)
    assert r.status_code in (413, 422)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_api.py -v
```
Expected: FAIL — `ModuleNotFoundError: authority.api`.

- [ ] **Step 3: Implement**

`src/authority/api.py`. Two things a naive version gets wrong, both fixed here: raising `HTTPException` from `@app.middleware("http")` escapes Starlette's exception handlers and yields a 500, so auth returns a `JSONResponse`; and the trace query must find task-scoped audit rows, whose `target` is the task id as text, not the prompt id.

```python
import json, uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from authority.outbox import drain_outbox
from authority.provider import MockProvider, PlanError
from authority.transitions import task_transition

FORBIDDEN_ROUTE_PATTERN = r"trad|order|kill|hud|launchd|plist|deploy|merge|push|secret"
MAX_PROMPT_CHARS = 200_000

def build_app(config, pool) -> FastAPI:
    app = FastAPI(title="OpenAlice Task-State Authority")
    app.state.config = config
    app.state.pool = pool
    app.state.provider = MockProvider(seed=0)

    @app.middleware("http")
    async def bearer_gate(request: Request, call_next):
        if request.url.path in ("/healthz", "/openapi.json", "/docs", "/redoc"):
            return await call_next(request)
        if request.headers.get("authorization") != f"Bearer {config.api_token}":
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "provider": "mock", "openai": "unconfigured",
                "lease_ttl_seconds": config.lease_ttl_seconds}

    class PromptIn(BaseModel):
        prompt: str

    @app.post("/prompts", status_code=201)
    async def submit_prompt(body: PromptIn):
        if not body.prompt.strip():
            return JSONResponse({"detail": "empty prompt"}, status_code=422)
        if len(body.prompt) > MAX_PROMPT_CHARS:
            return JSONResponse({"detail": "prompt too large"}, status_code=413)
        try:
            plan = await app.state.provider.plan(body.prompt, {})
        except PlanError as e:
            return JSONResponse({"detail": str(e)}, status_code=422)

        prompt_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "insert into prompts(id,source,actor,trace_id) "
                    "values($1,'chat',$2,$1)", prompt_id, "dashboard")
                await conn.execute(
                    "insert into roles(id,name,profile_version) values('r-plan','Planner',1) "
                    "on conflict (id,profile_version) do nothing")
                task_ids = []
                for t in plan.tasks:
                    task_ids.append(await conn.fetchval(
                        "insert into tasks(prompt_id,role_id,objective,priority,acceptance) "
                        "values($1,$2,$3,$4,$5::jsonb) returning id",
                        prompt_id, t["role_id"], t["objective"], t["priority"],
                        json.dumps(t["acceptance"])))
                await conn.execute(
                    "insert into audit_events(actor,action,target,outcome) "
                    "values('api','prompt_submitted',$1,'OK')", prompt_id)
        return {"prompt_id": prompt_id, "task_ids": task_ids}

    @app.get("/prompts/{prompt_id}/trace")
    async def trace_prompt(prompt_id: str):
        async with pool.acquire() as conn:
            tasks = await conn.fetch(
                "select id,state,fencing_token,assigned_slot_id,objective "
                "from tasks where prompt_id=$1 order by id", prompt_id)
            if not tasks:
                return JSONResponse({"detail": "unknown prompt"}, status_code=404)
            ids = [r["id"] for r in tasks]
            audit = await conn.fetch(
                "select at,actor,action,target,before_state,after_state,outcome "
                "  from audit_events "
                " where target = $1 or target = any($2::text[]) order by id",
                prompt_id, [str(i) for i in ids])
            events = await conn.fetch(
                "select id,event_type,emitted_at,published_at from outbox_events "
                "where prompt_id=$1 order by id", prompt_id)
        return {"prompt_id": prompt_id, "tasks": [dict(r) for r in tasks],
                "audit": [dict(r) for r in audit], "events": [dict(r) for r in events]}

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: int):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select id,state,fencing_token,assigned_slot_id,objective,repo,base_commit,"
                "allowed_paths,prohibited_paths from tasks where id=$1", task_id)
        if not row:
            return JSONResponse({"detail": "unknown task"}, status_code=404)
        return dict(row)

    class TransitionIn(BaseModel):
        to_state: str = Field(min_length=1, max_length=32)
        fencing_token: int
        evidence: dict | None = None
        actor: str = Field(default="holder", max_length=64)

    @app.post("/tasks/{task_id}/transition")
    async def transition(task_id: int, body: TransitionIn):
        async with pool.acquire() as conn:
            res = await task_transition(conn, task_id, body.to_state,
                                        body.fencing_token, body.evidence, body.actor)
        return {"ok": res.ok, "reason": res.reason, "new_state": res.new_state}

    @app.get("/events/outbox")
    async def drain(limit: int = 100):
        async with pool.acquire() as conn:
            return {"published": await drain_outbox(conn, _NullPublisher(), limit)}

    return app

class _NullPublisher:
    async def publish(self, event: dict) -> None:
        return None

def create_app(config, pool) -> FastAPI:
    return build_app(config, pool)
```

`src/authority/__main__.py` — the bind host comes from config, so a mis-set `AUTHORITY_BIND_HOST` fails closed rather than silently going public:

```python
import uvicorn
from authority.api import build_app
from authority.config import load_config
from authority.db import open_pool
import asyncio

async def main():
    cfg = load_config()
    pool = await open_pool(cfg.database_url)
    app = build_app(cfg, pool)
    try:
        uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port)
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_api.py -v
```
Expected: 9 passed. If `test_unauthenticated_request_is_rejected` returns 500 instead of 401, the middleware is raising rather than returning `JSONResponse` — fix the middleware, not the test.

- [ ] **Step 5: Verify the forbidden-route scan is not vacuous**

`test_no_declared_route_reaches_trading_hud_launchd_or_git_publish` passes only if the scan found routes and none matched. Prove it can fail by adding a decoy route in a scratch copy:

```bash
cp src/authority/api.py /tmp/api.keep
printf '\n@decoy\ndef _(): pass\n' >/dev/null
perl -0pi -e "s/    return app/    @app.post(\"\\\\/trading\\\\/arm\")\n    async def _decoy():\n        return {}\n\n    return app/" src/authority/api.py
uv run pytest tests/test_api.py -k forbidden_route -v
cp /tmp/api.keep src/authority/api.py && rm /tmp/api.keep
uv run pytest tests/test_api.py -k forbidden_route -v
```
Expected: decoy → FAIL listing `/trading/arm` in `leaked`. Restored → PASS. If the decoy does not trip it, the scan is decorative; fix the assertion before committing.

- [ ] **Step 6: Commit**

```bash
git add src/authority/api.py src/authority/__main__.py tests/test_api.py
git commit -m "feat: bearer-gated prompt intake and trace; C/D/E routes provably absent"
```

---

### Task 11: Teeth verification — prove the suite can fail

**Files:**
- Create: `scripts/prove_teeth.py`, `docs/TEETH.md`

**Interfaces:** Consumes the whole suite. Produces the artefact spec §17.12 requires: per-test evidence that its own mutant made it red.

- [ ] **Step 1: Write the mutation harness**

Each mutant is a textual edit to a real source file. The harness requires the anchor to appear **exactly once** — an anchor that matches zero times reports SKIP-INVALID rather than silently "passing", and one that matches twice is refused because it would mutate unintended code.

`scripts/prove_teeth.py`:

```python
"""Spec §17.12: prove each guard detects its own defect.

A test that stays green under the mutant it supposedly guards is decoration.
Each row names the file, the exact anchor, its replacement, and the test that
MUST go red. Anchors are verified to appear exactly once before mutating.
"""
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

MIGRATIONS = "src/authority/migrations"
MUTANTS = [
    ("row lock removed -> race must fail",
     f"{MIGRATIONS}/0002_transition.sql", "for update;", ";",
     "tests/test_race.py::test_exactly_one_of_twenty_concurrent_transitions_wins"),
    ("fencing guard disabled",
     f"{MIGRATIONS}/0002_transition.sql", "if v_token <> p_token then", "if false then",
     "tests/test_fencing.py::test_stale_token_cannot_write_even_on_a_legal_edge"),
    ("state vocabulary trigger gutted",
     f"{MIGRATIONS}/0001_schema.sql",
     "raise exception 'undocumented task state: %'", "raise notice 'x'",
     "tests/test_schema.py::test_undocumented_state_is_rejected"),
    ("append-only revoke dropped",
     f"{MIGRATIONS}/0001_schema.sql",
     "revoke update, delete, truncate on audit_events from authority_app;", "",
     "tests/test_schema.py::test_audit_events_cannot_be_updated_by_the_app_role"),
    ("mock slots allowed to reach QUEUED",
     f"{MIGRATIONS}/0002_transition.sql", "s.adapter <> 'mock'", "true",
     "tests/test_transitions.py::test_queued_requires_a_verified_non_mock_slot"),
    ("outbox no longer written with the transition",
     f"{MIGRATIONS}/0002_transition.sql",
     "insert into outbox_events(prompt_id,task_id,event_type,payload,dedupe_key)",
     "insert into audit_events(action,target) values('m','m')",
     "tests/test_transitions.py::test_legal_transition_writes_state_audit_and_outbox_atomically"),
    ("redaction disabled",
     f"{MIGRATIONS}/0001_schema.sql", "select regexp_replace(", "select (",
     "tests/test_redaction.py::test_a_secret_in_evidence_never_reaches_audit_events"),
    ("lease claim stops honouring an existing hold",
     f"{MIGRATIONS}/0004_lease_claim.sql", "and l.released_at is null)", "and false)",
     "tests/test_leases.py::test_a_second_claim_of_a_held_task_returns_none"),
    ("reaper hardcodes BLOCKED instead of policy",
     "src/authority/leases.py",
     'return "BLOCKED" if retryable else "QUARANTINED"', 'return "BLOCKED"',
     "tests/test_leases.py::test_gutting_retryability_routes_the_reaper_to_quarantined"),
    ("bearer auth gate removed",
     "src/authority/api.py",
     'return JSONResponse({"detail": "unauthorized"}, status_code=401)',
     'return await call_next(request)',
     "tests/test_api.py::test_unauthenticated_request_is_rejected"),
    ("forbidden-route pattern neutralised",
     "src/authority/api.py",
     'FORBIDDEN_ROUTE_PATTERN = r"trad|order|kill|hud|launchd|plist|deploy|merge|push|secret"',
     'FORBIDDEN_ROUTE_PATTERN = r"(?!never-match-xyz)"',
     "tests/test_api.py::test_no_declared_route_reaches_trading_hud_launchd_or_git_publish"),
]

def pytest_red(target: str) -> tuple[bool, int]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-x", "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True)
    return proc.returncode != 0, proc.returncode

bad: list[str] = []
for name, rel, needle, repl, target in MUTANTS:
    path = ROOT / rel
    original = path.read_text()
    hits = original.count(needle)
    if hits != 1:
        print(f"SKIP-INVALID  {name}: anchor hits={hits}, expected 1")
        bad.append(f"{name} (anchor not unique)")
        continue
    backup = path.with_name(path.name + ".bak")
    shutil.copyfile(path, backup)
    try:
        path.write_text(original.replace(needle, repl, 1))
        red, code = pytest_red(target)
        print(f"{'PASS' if red else 'FAIL'}       {name}  [pytest exit={code}]")
        if not red:
            bad.append(f"{name} (test stayed green)")
    finally:
        shutil.move(str(backup), str(path))

leftovers = list(ROOT.glob("src/**/*.bak")) + list(ROOT.glob("tests/**/*.bak"))
if leftovers:
    print(f"LEFTOVER BAK FILES: {leftovers}")
    bad.append("leftover .bak in source tree")

if bad:
    print(f"\n{len(bad)} problems — do NOT treat the suite as protective:")
    for b in bad:
        print(f"  - {b}")
    sys.exit(1)
print(f"\nall {len(MUTANTS)} mutants killed by their intended test")
```

- [ ] **Step 2: Verify the harness is not itself decorative**

The `hits != 1` guard is the whole point of a mutation harness — without it, a stale anchor reads as a passing test. Prove the guard bites:

```bash
cp scripts/prove_teeth.py /tmp/pt.keep
python3 - <<'PY'
import pathlib
p = pathlib.Path("scripts/prove_teeth.py")
s = p.read_text()
p.write_text(s.replace('"for update;"', '"for updateXX;"', 1))
PY
uv run python scripts/prove_teeth.py; echo "harness_exit=$?"
cp /tmp/pt.keep scripts/prove_teeth.py && rm /tmp/pt.keep
```
Expected: `SKIP-INVALID  row lock removed…: anchor hits=0, expected 1` and **`harness_exit=1`**. If it prints PASS or exits 0, the harness reports success from doing nothing — fix it before trusting a single line of its output.

- [ ] **Step 3: Run the real harness**

```bash
uv run python scripts/prove_teeth.py; echo "harness_exit=$?"
```
Expected: eleven `PASS` lines, `all 11 mutants killed…`, `harness_exit=0`. Every `FAIL` means that test is decoration: strengthen or write the real test, then re-run. **Do not commit a red harness as a known issue** — that is the failure mode that let four sessions on 2026-10-31 believe they held permissions.

- [ ] **Step 4: Confirm the tree is byte-identical after mutation**

```bash
git diff --stat
git status --porcelain
```
Expected: no modified files, only untracked additions from this task. A surviving `.bak` in `src/authority/migrations/` is how a stale-copy trap begins; the harness removes them in `finally` and refuses to exit clean if any remain.

- [ ] **Step 5: Write the ledger**

`docs/TEETH.md`, one row per mutant: test name, mutant applied, observed `pytest exit=`, verdict. It must state explicitly what this run **does not** cover, so the gap is owned rather than inherited:

- §17.5 (merge-back conflict) — **Plan 2**, no `worktrees` allocation exists yet.
- §17.6 full process-kill restart — partially covered by `test_a_new_process_sees_unpublished_events_and_drains_them_once` (new pool against the same database); killing a real `uvicorn` process lands with **Plan 3**, when a daemon exists.
- §17.10 (roster honesty) — **Plan 3**, adapters land there.

- [ ] **Step 6: Commit**

```bash
git add scripts/prove_teeth.py docs/TEETH.md
git commit -m "test: mutation harness proving each guard detects its own defect"
```

---

### Task 12: Runbook and status ledger

**Files:**
- Create: `README.md`, `docs/STATUS.md`

**Interfaces:** Produces the honest status vocabulary attached §14 demands, applied to this repo.

- [ ] **Step 1: Write the runbook**

`README.md` — prerequisite commands, run, test, and the two facts that save the next person hours: this repo has **no remote and none should be added without an owner decision** (spec §19 item 4), and `uv run pytest` requires `docker compose up -d db` first. Include the exact `DATABASE_URL`, the `PYTHONPATH`-free invocation (`pythonpath` is set in `pyproject.toml`), and how to read `docs/TEETH.md`.

- [ ] **Step 2: Write the status ledger**

`docs/STATUS.md`, mapping spec §20 item by item to *implemented / locally tested / integration tested / human reviewed / deployed / production verified*. It must say plainly:

- DoD #3 **BLOCKED** — no `OPENAI_*` credential exists on either host; `LLM_PROVIDER=groq`; `MockProvider` is a test double, not a reasoning engine.
- DoD #6 **UNVERIFIED** — measured 2026-10-31: zero opencode sessions updated in 24 h on the laptop, none in 14 days on the mini; the ten `ORG-*` session IDs in `~/OpenAlice_10K_Orchestration/discovery-wave1.md` are absent from both hosts. No probe-verified slot exists, so nothing can legitimately reach `QUEUED` yet.
- Worktree pool, merge-back, adapters, dashboard: **not started** — Plans 2 and 3.
- Nothing is deployed. No port is bound except a developer's own `127.0.0.1:4810`.

- [ ] **Step 3: Verify the ledger against command output, not memory**

```bash
docker compose up -d db
uv run pytest -q; echo "suite_exit=$?"
uv run python scripts/prove_teeth.py; echo "harness_exit=$?"
git remote -v; echo "remotes_above_should_be_empty"
git status --porcelain; echo "should be clean"
```
Then cross-check every claim in `docs/STATUS.md` against what those commands actually printed. A claim with no command behind it gets deleted, not softened.

- [ ] **Step 4: Confirm nothing outside this repo was touched**

```bash
git -C ~/openalice-fleet status --porcelain
git -C ~/openalice-fleet rev-parse --short HEAD
git -C ~/openalice-fleet rev-list --left-right --count origin/main...HEAD
```
Expected: exactly the three pre-existing untracked lines (`?? ORCHESTRATION_DISCOVERY_2026-10-31.md`, `?? coordination/`, `?? fleet-worktrees/`), HEAD still `df02580`, still `0 10`. Anything else means this plan leaked outside its repo — stop and report it.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/STATUS.md
git commit -m "docs: runbook and status ledger; DoD 3 blocked, DoD 6 unverified"
```

---

## Definition of done for this plan

All twelve tasks committed. `uv run pytest -q` green. `uv run python scripts/prove_teeth.py` exits 0 **and** Step 2 of Task 11 demonstrated that the harness reports SKIP-INVALID plus exit 1 on a broken anchor. `git remote -v` still empty. `git status` clean. `~/openalice-fleet` unchanged per Task 12 Step 4. `docs/STATUS.md` claims match printed command output line for line.

**Not in this plan, by design:** worktree pool and merge-back (Plan 2), adapters and dashboard (Plan 3), the OpenAI credential, HUD provenance, and any git remote. Each is recorded in spec §19 as an owner decision, and none may be quietly promoted to "done" by an executor reading only this file.
