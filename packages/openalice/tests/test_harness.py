BASE_TABLES = {"prompts", "roles", "worker_slots", "state_edges", "tasks",
               "leases", "worktrees", "merge_queue", "outbox_events", "audit_events"}


async def test_pool_connects_and_migrations_are_applied(conn):
    """Task 1 asserted `[tablename] == []`, which was only ever a proxy for "the
    fixture rebuilt schema `public` from nothing" — it held because no migration
    existed yet, and it would also have passed with the migrations directory
    missing entirely. 0001_schema.sql now lands ten tables, so the proxy is false
    and the underlying invariant is asserted directly: the connection works AND the
    migration applied. Subset, not equality, so 0002+ may add tables without
    breaking this harness guard."""
    rows = await conn.fetch("select tablename from pg_tables where schemaname='public'")
    tables = {r["tablename"] for r in rows}
    assert BASE_TABLES <= tables, f"migration did not apply: missing {BASE_TABLES - tables}"


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
