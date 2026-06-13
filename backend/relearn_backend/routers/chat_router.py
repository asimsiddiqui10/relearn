"""Chat sessions + the /chat SSE proxy (spec/01).

The backend authenticates, attaches scope, persists the user message, then
forwards to the AI service and pipes its SSE stream back unmodified. It holds no
AI logic.
"""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import ChatMessage, ChatSession

from relearn_backend.access import require_member
from relearn_backend.auth import Principal, current_principal
from relearn_backend.config import get_settings
from relearn_backend.db import get_session
from relearn_backend.schemas import (
    ChatMessageOut,
    ChatSendRequest,
    ChatSessionCreate,
    ChatSessionOut,
)

router = APIRouter(tags=["chat"])


@router.post("/spaces/{space_id}/chat/sessions", response_model=ChatSessionOut, status_code=201)
async def create_session(
    space_id: uuid.UUID,
    body: ChatSessionCreate,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_member(session, space_id, principal.user_id)
    cs = ChatSession(space_id=space_id, user_id=principal.user_id, title=body.title)
    session.add(cs)
    await session.commit()
    return cs


@router.get("/spaces/{space_id}/chat/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    space_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_member(session, space_id, principal.user_id)
    rows = (
        await session.execute(
            select(ChatSession)
            .where(ChatSession.space_id == space_id, ChatSession.user_id == principal.user_id)
            .order_by(ChatSession.created_at.desc())
        )
    ).scalars().all()
    return rows


async def _load_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: str
) -> ChatSession:
    cs = (
        await session.execute(select(ChatSession).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    if cs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    await require_member(session, cs.space_id, user_id)
    return cs


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    session_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await _load_session(session, session_id, principal.user_id)
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return rows


@router.post("/chat/sessions/{session_id}/message")
async def send_message(
    session_id: uuid.UUID,
    body: ChatSendRequest,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    cs = await _load_session(session, session_id, principal.user_id)

    # persist the user message (backend owns user rows, spec/02), then commit so
    # the AI service — reading the same DB — sees it as history.
    session.add(ChatMessage(session_id=session_id, role="user", content=body.message))
    # auto-title an untitled session from its first message (sidebar labels)
    if not cs.title:
        cs.title = body.message[:60] + ("…" if len(body.message) > 60 else "")
    await session.commit()

    settings = get_settings()

    async def proxy():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{settings.ai_service_url}/chat",
                json={
                    "session_id": str(session_id),
                    "space_id": str(cs.space_id),
                    "message": body.message,
                },
                headers={"X-Internal-Token": settings.internal_token},
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    yield f"event: error\ndata: {{\"message\": \"ai service {resp.status_code}\"}}\n\n"
                    return
                async for chunk in resp.aiter_raw():
                    yield chunk

    return StreamingResponse(proxy(), media_type="text/event-stream")
