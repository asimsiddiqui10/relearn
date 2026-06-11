"""End-to-end ingestion via parse-cache replay — no Datalab key required.

Requires the docker-compose stack (postgres + minio) up and the schema migrated.
Seeds parses/{sha}.json directly so the pipeline skips Datalab entirely.
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text

from relearn_db.engine import create_engine_and_sessionmaker
from relearn_db.models import Chunk, Document, IngestJob, Resource, Space, StructureNode, User

from relearn_ai import storage
from relearn_ai.ingestion.pipeline import run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "marker_sample.json"
os.environ.setdefault("EMBEDDINGS_FAKE", "1")

pytestmark = pytest.mark.asyncio


async def _stack_available() -> bool:
    try:
        engine, _ = create_engine_and_sessionmaker()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
async def session():
    if not await _stack_available():
        pytest.skip("docker-compose stack not running")
    engine, maker = create_engine_and_sessionmaker()
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_pipeline_replays_from_cache(session):
    checksum = f"test{uuid.uuid4().hex}"

    # seed: parse cache + a placeholder PDF object
    await storage.put_json(storage.parse_key(checksum), json.loads(FIXTURE.read_text()))
    await storage.put_bytes(storage.pdf_key(checksum), b"%PDF-1.4 placeholder")

    user = User(id=f"u_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@test.dev", name="Test")
    session.add(user)
    await session.flush()
    space = Space(owner_user_id=user.id, name="Test Space")
    session.add(space)
    await session.flush()
    resource = Resource(
        space_id=space.id, type="document", title="Biology", uploaded_by=user.id, status="pending"
    )
    session.add(resource)
    await session.flush()
    job = IngestJob(resource_id=resource.id, status="queued")
    session.add(job)
    await session.commit()

    await run_pipeline(session, job.id, checksum=checksum, doc_type="textbook", title="Biology")

    await session.refresh(resource)
    await session.refresh(job)
    assert resource.status == "ready", f"job error: {job.error}"
    assert job.status == "succeeded"

    document = (
        await session.execute(select(Document).where(Document.id == resource.document_id))
    ).scalar_one()
    assert document.status == "ready"
    assert document.metadata_json["page_dimensions"]["0"] == [612.0, 792.0]

    nodes = (
        await session.execute(
            select(StructureNode).where(StructureNode.document_id == document.id)
        )
    ).scalars().all()
    assert {n.heading_text for n in nodes} >= {
        "Chapter 1 Cell Biology", "1.1 The Mitochondrion", "1.2 Cellular Respiration"
    }

    chunks = (
        await session.execute(select(Chunk).where(Chunk.document_id == document.id))
    ).scalars().all()
    assert len(chunks) >= 6
    # embeddings written, tsv populated by the generated column
    assert all(c.embedding is not None for c in chunks)


async def test_dedup_short_circuits(session):
    checksum = f"test{uuid.uuid4().hex}"
    await storage.put_json(storage.parse_key(checksum), json.loads(FIXTURE.read_text()))
    await storage.put_bytes(storage.pdf_key(checksum), b"%PDF-1.4 placeholder")

    user = User(id=f"u_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@test.dev")
    session.add(user)
    await session.flush()
    space = Space(owner_user_id=user.id, name="Dedup Space")
    session.add(space)
    await session.flush()

    async def ingest_once() -> uuid.UUID:
        resource = Resource(
            space_id=space.id, type="document", title="Bio", uploaded_by=user.id, status="pending"
        )
        session.add(resource)
        await session.flush()
        job = IngestJob(resource_id=resource.id, status="queued")
        session.add(job)
        await session.commit()
        await run_pipeline(session, job.id, checksum=checksum, doc_type="textbook", title="Bio")
        await session.refresh(resource)
        return resource.document_id

    doc1 = await ingest_once()
    doc2 = await ingest_once()
    assert doc1 == doc2  # second upload reused the existing document
