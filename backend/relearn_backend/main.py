"""Backend gateway — the only public door (spec/01). Holds zero AI logic."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from relearn_backend.config import get_settings
from relearn_backend.db import dispose_engine
from relearn_backend.routers import (
    auth_router,
    chat_router,
    documents_router,
    resources_router,
    spaces_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_engine()


app = FastAPI(title="relearn-backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(spaces_router.router)
app.include_router(resources_router.router)
app.include_router(documents_router.router)
app.include_router(chat_router.router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
