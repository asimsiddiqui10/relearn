"""AI service HTTP app (internal-only; trusts the backend's internal token).

/chat streams the agent loop as SSE. The backend proxies this stream to the
browser unmodified — the AI service never sees end users.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from relearn_db.engine import create_engine_and_sessionmaker

from relearn_ai.config import get_settings
from relearn_ai.service.runner import run_chat_turn

app = FastAPI(title="relearn-ai", docs_url=None, redoc_url=None)

_engine, _sessionmaker = create_engine_and_sessionmaker(get_settings().database_url)


async def require_internal_token(x_internal_token: str = Header(default="")) -> None:
    if x_internal_token != get_settings().internal_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad internal token")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    space_id: uuid.UUID
    message: str


@app.post("/chat", dependencies=[Depends(require_internal_token)])
async def chat(req: ChatRequest):
    async def event_source():
        async with _sessionmaker() as session:
            async for event in run_chat_turn(
                session,
                session_id=req.session_id,
                space_id=req.space_id,
                user_message=req.message,
            ):
                yield event.sse()

    return EventSourceResponse(event_source())
