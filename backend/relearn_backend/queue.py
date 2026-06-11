"""arq enqueue side (the worker lives in the AI service)."""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from relearn_backend.config import get_settings

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue_ingest(job_id: str, *, checksum: str, doc_type: str, title: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job("ingest", job_id, checksum=checksum, doc_type=doc_type, title=title)
