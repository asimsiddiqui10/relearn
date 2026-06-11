"""arq ingestion worker (spec/01: separate process, same codebase).

Run: cd ai && uv run arq app.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import uuid

from arq.connections import RedisSettings

from relearn_db.engine import create_engine_and_sessionmaker

from relearn_ai.config import get_settings
from relearn_ai.ingestion.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def ingest(ctx, job_id: str, *, checksum: str, doc_type: str, title: str) -> None:
    async with ctx["sessionmaker"]() as session:
        await run_pipeline(
            session,
            uuid.UUID(job_id),
            checksum=checksum,
            doc_type=doc_type,
            title=title,
        )


async def startup(ctx) -> None:
    engine, sessionmaker = create_engine_and_sessionmaker()
    ctx["engine"] = engine
    ctx["sessionmaker"] = sessionmaker


async def shutdown(ctx) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [ingest]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 1800  # Datalab parse of a large book can take a while
