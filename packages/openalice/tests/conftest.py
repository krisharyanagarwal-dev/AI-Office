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
    # Invariant (ruling T2-B): keep this pool function-scoped — one set of physical
    # connections per test. A widened pool carries a test's SET ROLE into the next
    # _migrate(), because Postgres excludes `role` from asyncpg's RESET ALL.
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
        # Teardown, not a trailing line in the test body: a failing test skips its own
        # last statement, but pytest still runs this.
        await c.execute("reset role")
