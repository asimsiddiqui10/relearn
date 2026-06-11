"""Full chat turn through the runner: persists agent_run, agent_run_events, and
the assistant chat_message — with a scripted fake model. Needs the stack."""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text

from relearn_db.engine import create_engine_and_sessionmaker
from relearn_db.models import (
    AgentRun,
    AgentRunEvent,
    ChatMessage,
    ChatSession,
    IngestJob,
    Resource,
    Space,
    User,
)

from relearn_ai import storage
from relearn_ai.ingestion.pipeline import run_pipeline
from relearn_ai.llm.stream import Delta, ToolCall
from relearn_ai.service.runner import run_chat_turn

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


def _scripted(*turns):
    calls = list(turns)
    i = {"n": 0}

    async def streamer(messages, *, tools=None):
        turn = calls[i["n"]]
        i["n"] += 1
        if isinstance(turn, str):
            yield Delta(text=turn)
            yield Delta(done=True, tool_calls=[])
        else:
            yield Delta(done=True, tool_calls=turn)

    return streamer


async def test_chat_turn_persists_run_events_and_answer():
    if not await _stack_up():
        pytest.skip("compose stack not running")
    engine, maker = create_engine_and_sessionmaker()
    async with maker() as session:
        # ingest a doc
        checksum = f"chat{uuid.uuid4().hex}"
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

        cs = ChatSession(space_id=space.id, user_id=user.id, title="t")
        session.add(cs)
        # the user message would be persisted by the backend; do it here
        await session.flush()
        session.add(ChatMessage(session_id=cs.id, role="user", content="What do mitochondria do?"))
        await session.commit()

        streamer = _scripted(
            [ToolCall(id="c1", name="search_chunks",
                      arguments={"query": "mitochondrion respiration"})],
            "Mitochondria make ATP via respiration [E1].",
        )
        events = [
            e async for e in run_chat_turn(
                session, session_id=cs.id, space_id=space.id,
                user_message="What do mitochondria do?", streamer=streamer,
            )
        ]
        assert events[0].type == "run_started"
        assert events[-1].type == "run_completed"

        # one agent_run, completed
        run = (
            await session.execute(select(AgentRun).where(AgentRun.session_id == cs.id))
        ).scalar_one()
        assert run.status == "completed"

        # events persisted append-only with contiguous seq
        run_events = (
            await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.seq)
            )
        ).scalars().all()
        assert [e.seq for e in run_events] == list(range(len(run_events)))
        assert len(run_events) == len(events)

        # assistant message saved with citations
        assistant = (
            await session.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == cs.id, ChatMessage.role == "assistant"
                )
            )
        ).scalar_one()
        assert "ATP" in assistant.content
        assert assistant.citations_json and "E1" in assistant.citations_json
    await engine.dispose()
