"""Async engine/session factory shared by backend and AI service."""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://relearn:relearn@localhost:5432/relearn"
    )


def create_engine_and_sessionmaker(url: str | None = None):
    engine = create_async_engine(url or database_url(), pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
