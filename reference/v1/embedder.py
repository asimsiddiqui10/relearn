"""Embedder Service — generates vector embeddings using Gemini or OpenAI."""

from __future__ import annotations

import logging

from app.rag.config import settings
from app.rag.tracing import observe, update_current_observation

logger = logging.getLogger(__name__)

_GEMINI_BATCH_SIZE = 100
_OPENAI_BATCH_SIZE = 2048


@observe(name="embed_texts")
async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    # Gemini rejects empty-content batches with INVALID_ARGUMENT. Substitute a
    # single-space placeholder so indices stay aligned with caller-side chunk
    # lists, and downstream code can tell these apart by near-zero content.
    safe_texts = [t if t and t.strip() else " " for t in texts]

    update_current_observation(
        input={
            "text_count": len(safe_texts),
            "empty_count": sum(1 for t in texts if not (t and t.strip())),
            "model": settings.EMBEDDING_MODEL,
            "dim": settings.EMBEDDING_DIM,
        },
    )

    if settings.GEMINI_API_KEY:
        try:
            return await _embed_gemini(safe_texts)
        except Exception:
            logger.exception("Gemini embedding failed")

    if settings.OPENAI_API_KEY:
        try:
            return await _embed_openai(safe_texts)
        except Exception:
            logger.exception("OpenAI embedding failed")

    logger.warning(
        "No usable embedding provider — returning zero vectors for %d texts",
        len(safe_texts),
    )
    return [[0.0] * settings.EMBEDDING_DIM for _ in safe_texts]


async def _embed_gemini(texts: list[str]) -> list[list[float]]:
    import asyncio
    from google import genai
    from google.genai.types import EmbedContentConfig

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    all_embeddings: list[list[float]] = []
    loop = asyncio.get_running_loop()

    for start in range(0, len(texts), _GEMINI_BATCH_SIZE):
        batch = texts[start : start + _GEMINI_BATCH_SIZE]

        def _call(b=batch):
            result = client.models.embed_content(
                model=settings.EMBEDDING_MODEL,
                contents=b,
                config=EmbedContentConfig(output_dimensionality=settings.EMBEDDING_DIM),
            )
            return [e.values for e in result.embeddings]

        batch_embeddings = await loop.run_in_executor(None, _call)
        all_embeddings.extend(batch_embeddings)

    logger.info(
        "Gemini embedded %d texts with model %s dim=%d",
        len(texts),
        settings.EMBEDDING_MODEL,
        settings.EMBEDDING_DIM,
    )
    return all_embeddings


async def _embed_openai(texts: list[str]) -> list[list[float]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    all_embeddings: list[list[float]] = []
    model = settings.EMBEDDING_MODEL
    if model.startswith("models/"):
        logger.warning(
            "EMBEDDING_MODEL=%s looks like a Gemini model; using OpenAI default text-embedding-3-small",
            model,
        )
        model = "text-embedding-3-small"

    for start in range(0, len(texts), _OPENAI_BATCH_SIZE):
        batch = texts[start : start + _OPENAI_BATCH_SIZE]
        payload: dict = {"model": model, "input": batch}
        if model.startswith("text-embedding-3"):
            payload["dimensions"] = settings.EMBEDDING_DIM
        response = await client.embeddings.create(**payload)
        all_embeddings.extend([item.embedding for item in response.data])

    logger.info("OpenAI embedded %d texts with model %s", len(texts), model)
    return all_embeddings
