from __future__ import annotations
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.db.session import AsyncSessionLocal
from app.config import settings

_redis_pool: Optional[aioredis.Redis] = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_pool
