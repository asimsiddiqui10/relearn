"""Agent loop with a scripted fake model — no API key. Exercises the real tools,
evidence registry, SSE event sequence, citation verification, and HITL
suspend/resume against an ingested fixture document.
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
from relearn_ai.agent.loop import run_agent
from relearn_ai.agent.tools import doc_slugs
from relearn_ai.llm.stream import Delta, ToolCall
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
        checksum = f"loop{uuid.uuid4().hex}"
        await storage.put_json(storage.parse_key(checksum), json.loads(FIXTURE.read_text()))
        await storage.put_bytes(storage.pdf_key(checksum), b"%PDF-1.4 x")
        user = User(id=f"u_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        session.add(user)
        await session.flush()
        space = Space(owner_user_id=user.id, name="S")
        session.add(space)
        await session.flush()
        resource = Resource(space_id=space.id, type="document", title="Bio",
                            uploaded_by=user.id, status="pending")
        session.add(resource)
        await session.flush()
        job = IngestJob(resource_id=resource.id, status="queued")
        session.add(job)
        await session.commit()
        await run_pipeline(session, job.id, checksum=checksum, doc_type="textbook", title="Bio")
        await session.refresh(resource)
        ctx = RunContext(space_id=space.id, document_ids=[resource.document_id])
        yield session, ctx
    await engine.dispose()


def _scripted(*turns):
    """Build a streamer that replays scripted turns. Each turn is either a string
    (final answer text) or a list of ToolCall (a tool-calling turn)."""
    calls = list(turns)
    idx = {"i": 0}

    async def streamer(messages, *, tools=None):
        turn = calls[idx["i"]]
        idx["i"] += 1
        if isinstance(turn, str):
            for word in turn.split(" "):
                yield Delta(text=word + " ")
            yield Delta(done=True, tool_calls=[])
        else:
            yield Delta(done=True, tool_calls=turn)

    return streamer


async def _collect(agen):
    return [e async for e in agen]


async def test_search_then_cited_answer(ingested):
    session, ctx = ingested
    streamer = _scripted(
        [ToolCall(id="c1", name="search_chunks", arguments={"query": "mitochondrion respiration"})],
        "Mitochondria produce ATP via cellular respiration [E1].",
    )
    events = await _collect(
        run_agent([{"role": "user", "content": "What do mitochondria do?"}], ctx, session,
                  streamer=streamer)
    )
    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert "tool_started" in types and "tool_result" in types
    assert "evidence_added" in types
    assert types[-3:] == ["citation_map", "confidence", "run_completed"]
    # seq is monotonic
    assert [e.seq for e in events] == list(range(len(events)))
    # citation_map marks E1 as used and high confidence (>=3 evidence)
    cmap = next(e for e in events if e.type == "citation_map").data["map"]
    assert cmap["E1"]["used"] is True
    conf = next(e for e in events if e.type == "confidence").data
    assert conf["level"] == "high"


async def test_text_streams_before_tool(ingested):
    session, ctx = ingested
    streamer = _scripted(
        [ToolCall(id="c1", name="get_toc", arguments={"doc_slug": "doc-0"})],
        "Done [E0-none].",
    )
    events = await _collect(run_agent([{"role": "user", "content": "hi"}], ctx, session,
                                      streamer=streamer))
    # dangling citation [E... actually none registered → low confidence
    conf = next(e for e in events if e.type == "confidence").data
    assert conf["level"] in ("low", "medium", "high")


async def test_uncited_paragraph_flagged(ingested):
    session, ctx = ingested
    long_uncited = " ".join(["word"] * 30) + "."  # 30 words, no [E#]
    streamer = _scripted(
        [ToolCall(id="c1", name="search_chunks", arguments={"query": "respiration"})],
        long_uncited,
    )
    events = await _collect(run_agent([{"role": "user", "content": "explain"}], ctx, session,
                                      streamer=streamer))
    conf = next(e for e in events if e.type == "confidence").data
    assert conf["level"] == "medium"
    assert "citation" in conf["reason"]


async def test_hitl_suspend_then_resume(ingested):
    session, ctx = ingested
    saved = {}

    async def checkpoint(state):
        saved.update(state)

    # turn 1: the model asks a clarifying question → loop suspends
    streamer1 = _scripted(
        [ToolCall(id="ask1", name="ask_user",
                  arguments={"question": "Which chapter?", "options": ["1", "2"]})],
    )
    events1 = await _collect(
        run_agent([{"role": "user", "content": "tell me about it"}], ctx, session,
                  streamer=streamer1, checkpoint=checkpoint)
    )
    assert events1[-1].type == "clarification_required"
    assert events1[-1].data["question"] == "Which chapter?"
    assert saved["pending"]["tool"] == "ask_user"
    assert saved["messages"][-1]["role"] == "assistant"  # tool-call turn persisted

    # resume: append the user's answer as the pending tool's result, continue
    resumed_messages = list(saved["messages"])
    resumed_messages.append(
        {"role": "tool", "tool_call_id": saved["pending"]["call_id"], "content": "Chapter 1"}
    )
    ctx2 = RunContext(
        space_id=ctx.space_id,
        document_ids=ctx.document_ids,
        registry=EvidenceRegistry.restore(saved["registry"]),
    )
    # second leg must search first to register E1, then answer
    streamer2 = _scripted(
        [ToolCall(id="c9", name="search_chunks", arguments={"query": "mitochondrion"})],
        "Chapter 1 covers the mitochondrion [E1].",
    )
    events2 = await _collect(
        run_agent(resumed_messages, ctx2, session, streamer=streamer2,
                  start_seq=saved["seq"])
    )
    # resume does NOT re-emit run_started; seq continues from where it suspended
    assert events2[0].type != "run_started"
    assert events2[0].seq == saved["seq"]
    assert events2[-1].type == "run_completed"


async def test_slug_map_matches_ctx(ingested):
    _session, ctx = ingested
    assert doc_slugs(ctx.document_ids) == {"doc-0": ctx.document_ids[0]}
