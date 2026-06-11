"""Async engine/session factory shared by backend and AI service."""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://relearn:relearn@localhost:5432/relearn"
    )


def create_engine_and_sessionmaker(url: str | None = None):
    # pool_recycle (not pool_pre_ping) handles stale connections: pre-ping's async
    # path is incompatible with asyncpg under multiple event loops (test loops).
    engine = create_async_engine(url or database_url(), pool_recycle=1800)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
