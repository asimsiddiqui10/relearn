"""Retrieval tools + evidence registry against a freshly ingested fixture doc.

Needs the compose stack (postgres + minio). EMBEDDINGS_FAKE gives deterministic
vectors so hybrid search runs without the BGE-M3 download — lexical (tsv) ranking
still does the real work; semantic just contributes deterministic RRF ranks.
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from relearn_db.engine import create_engine_and_sessionmaker
from relearn_db.models import IngestJob, Resource, Space, User

from relearn_ai import storage
from relearn_ai.agent.evidence import EvidenceRegistry, RunContext
from relearn_ai.agent.tools import TOOLS, doc_slugs
from relearn_ai.agent.tools.retrieval_tools import (
    ExpandChunkArgs,
    GetTocArgs,
    ReadSectionArgs,
    SearchChunksArgs,
)
from relearn_ai.ingestion.pipeline import run_pipeline

os.environ.setdefault("EMBEDDINGS_FAKE", "1")
FIXTURE = Path(__file__).parent / "fixtures" / "marker_sample.json"
pytestmark = pytest.mark.asyncio


async def _stack_up() -> bool:
    try:
        engine, _ = create_engine_and_sessionmaker()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
async def ingested():
    if not await _stack_up():
        pytest.skip("compose stack not running")
    engine, maker = create_engine_and_sessionmaker()
    async with maker() as session:
        checksum = f"tool{uuid.uuid4().hex}"
        await storage.put_json(storage.parse_key(checksum), json.loads(FIXTURE.read_text()))
        await storage.put_bytes(storage.pdf_key(checksum), b"%PDF-1.4 x")

        user = User(id=f"u_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        session.add(user)
        await session.flush()
        space = Space(owner_user_id=user.id, name="S")
        session.add(space)
        await session.flush()
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

        ctx = RunContext(
            space_id=space.id,
            document_ids=[resource.document_id],
            registry=EvidenceRegistry(),
        )
        yield session, ctx
    await engine.dispose()


async def test_search_registers_evidence(ingested):
    session, ctx = ingested
    res = await TOOLS["search_chunks"].run(
        SearchChunksArgs(query="mitochondrion ATP respiration"), ctx, session
    )
    assert res.payload["results"], "expected hits for an on-topic query"
    first = res.payload["results"][0]
    assert first["eid"].startswith("E")
    assert first["doc"] == "doc-0"
    # evidence resolvable back to chunk/page/bbox
    item = ctx.registry.get(first["eid"])
    assert item is not None and item.page is not None
    assert res.summary.startswith("Found") and "sections" in res.summary


async def test_get_toc_then_read_section(ingested):
    session, ctx = ingested
    toc = await TOOLS["get_toc"].run(GetTocArgs(doc_slug="doc-0"), ctx, session)
    headings = [n["heading"] for n in toc.payload["toc"]]
    assert "Chapter 1 Cell Biology" in headings

    mito = next(n for n in toc.payload["toc"] if n["heading"] == "1.1 The Mitochondrion")
    sec = await TOOLS["read_section"].run(ReadSectionArgs(node_id=mito["node_id"]), ctx, session)
    assert sec.payload["passages"]
    assert all(p["eid"].startswith("E") for p in sec.payload["passages"])


async def test_expand_chunk_widens_context(ingested):
    session, ctx = ingested
    search = await TOOLS["search_chunks"].run(SearchChunksArgs(query="respiration"), ctx, session)
    eid = search.payload["results"][0]["eid"]
    exp = await TOOLS["expand_chunk"].run(ExpandChunkArgs(eid=eid), ctx, session)
    assert exp.payload["passages"]


async def test_scope_enforced_empty_for_foreign_doc(ingested):
    session, ctx = ingested
    # a context scoped to a non-existent doc must return nothing (fail closed)
    foreign = RunContext(space_id=ctx.space_id, document_ids=[uuid.uuid4()])
    res = await TOOLS["search_chunks"].run(
        SearchChunksArgs(query="mitochondrion"), foreign, session
    )
    assert res.payload["results"] == []


async def test_doc_slug_mapping():
    ids = [uuid.uuid4(), uuid.uuid4()]
    slugs = doc_slugs(ids)
    assert slugs == {"doc-0": ids[0], "doc-1": ids[1]}


async def test_evidence_registry_dedupes_and_snapshots():
    reg = EvidenceRegistry()
    cid, did = uuid.uuid4(), uuid.uuid4()
    a = reg.register(chunk_id=cid, document_id=did, page=1, bbox=None, polygon=None,
                     heading_breadcrumb="H", text="t")
    b = reg.register(chunk_id=cid, document_id=did, page=1, bbox=None, polygon=None,
                     heading_breadcrumb="H", text="t")
    assert a.eid == b.eid  # same chunk → same eid
    restored = EvidenceRegistry.restore(reg.snapshot())
    assert restored.get(a.eid) is not None
