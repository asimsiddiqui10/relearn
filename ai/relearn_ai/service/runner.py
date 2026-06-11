"""Run the agent loop for a chat turn and persist its event stream.

The AI service trusts the backend (internal token); it never validates end users.
Scope comes in as space_id; the runner resolves the space's ready documents and
enforces them as the agent's allowed corpus.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import (
    AgentRun,
    AgentRunEvent,
    ChatMessage,
    Document,
    Resource,
    Space,
)

from relearn_ai.agent import events as ev
from relearn_ai.agent.evidence import EvidenceRegistry, RunContext
from relearn_ai.agent.loop import Streamer, default_streamer, run_agent
from relearn_ai.agent.prompt import SpaceContext, build_system_prompt
from relearn_ai.agent.tools import doc_slugs

# how many prior turns to replay verbatim (rolling-compaction summary is spec/03 later)
_HISTORY_TURNS = 12


async def _space_context(session: AsyncSession, space_id: uuid.UUID) -> tuple[SpaceContext, list]:
    space = (await session.execute(select(Space).where(Space.id == space_id))).scalar_one()
    rows = (
        await session.execute(
            select(Document.id, Resource.title, Document.summary)
            .join(Resource, Resource.document_id == Document.id)
            .where(Document.space_id == space_id, Document.status == "ready")
            .order_by(Document.created_at)
        )
    ).all()
    document_ids = [r[0] for r in rows]
    slugs = doc_slugs(document_ids)
    slug_by_id = {did: slug for slug, did in slugs.items()}
    docs = [
        {"slug": slug_by_id[r[0]], "title": r[1], "summary": r[2]}
        for r in rows
    ]
    ctx_docs = SpaceContext(
        name=space.name, instructions=space.instructions, memory=space.memory, documents=docs
    )
    return ctx_docs, document_ids


async def _history(session: AsyncSession, session_id: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(_HISTORY_TURNS * 2)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "assistant")]


async def _persist_event(session: AsyncSession, run_id: uuid.UUID, event: ev.Event) -> None:
    session.add(
        AgentRunEvent(
            run_id=run_id, seq=event.seq, event_type=event.type, payload_json=event.data
        )
    )
    await session.commit()


async def run_chat_turn(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    space_id: uuid.UUID,
    user_message: str,
    streamer: Streamer = default_streamer,
) -> AsyncIterator[ev.Event]:
    """Create a run, stream + persist its events, and save the assistant reply."""
    space_ctx, document_ids = await _space_context(session, space_id)
    system = build_system_prompt(space_ctx)
    history = await _history(session, session_id)
    messages = [{"role": "system", "content": system}, *history,
                {"role": "user", "content": user_message}]

    run = AgentRun(session_id=session_id, mode="interactive", status="running", model="agent")
    session.add(run)
    await session.flush()
    run_id = run.id

    ctx = RunContext(space_id=space_id, document_ids=document_ids, registry=EvidenceRegistry())
    answer_parts: list[str] = []
    citations: dict | None = None

    async def checkpoint(state: dict) -> None:
        run.status = "suspended"
        run.state_json = state
        await session.commit()

    try:
        async for event in run_agent(
            messages, ctx, session, checkpoint=checkpoint, streamer=streamer
        ):
            if event.type == "text_delta":
                answer_parts.append(event.data["text"])
            elif event.type == "citation_map":
                citations = event.data["map"]
            await _persist_event(session, run_id, event)
            yield event

        # persist the assistant message (AI service owns assistant rows, spec/02)
        if run.status != "suspended":
            session.add(
                ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content="".join(answer_parts),
                    citations_json=citations,
                )
            )
            run.status = "completed"
            await session.commit()
    except Exception:
        run.status = "failed"
        await session.commit()
        raise
