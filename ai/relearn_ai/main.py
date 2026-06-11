"""AI service HTTP app. Phase 0: health only — the agent runtime arrives in Phase 1."""

from fastapi import FastAPI

app = FastAPI(title="relearn-ai", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
