import asyncpg
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from typing import Optional

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Global connection pool
_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    """Initialize the database connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,
            max_size=20,
            command_timeout=30,
            server_settings={
                'jit': 'off'  
            }
        )
    return _pool

async def close_db_pool():
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def get_db_pool() -> asyncpg.Pool:
    """Get the database connection pool."""
    if _pool is None:
        await init_db_pool()
    return _pool

@asynccontextmanager
async def get_db_connection():
    """Async context manager for database connections from pool."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
