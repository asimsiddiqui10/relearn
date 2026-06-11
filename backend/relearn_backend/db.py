"""DB session dependency (shared schema via relearn_db)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.engine import create_engine_and_sessionmaker

from relearn_backend.config import get_settings

_engine, _sessionmaker = create_engine_and_sessionmaker(get_settings().database_url)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _sessionmaker() as session:
        yield session


async def dispose_engine() -> None:
    await _engine.dispose()
