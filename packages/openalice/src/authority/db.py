import os

import asyncpg


async def open_pool(dsn: str | None = None) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn or os.environ["DATABASE_URL"], min_size=1, max_size=25
    )
