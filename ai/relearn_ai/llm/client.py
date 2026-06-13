"""Role-based LLM access (spec/06): `complete(role=...)` and `embed(texts)`.

Application code never names a provider. The openai_compat adapter covers every
hosted provider; embeddings run locally (BGE-M3). Retries: exponential backoff,
then the role's fallback alias, then error (spec/03 failure policy).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging


from openai import AsyncOpenAI

from relearn_ai.config import get_settings
from relearn_ai.llm.registry import ModelConfig, get_registry
from relearn_ai.observability import observe

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_EMBED_BATCH_SIZE = 64


class LLMError(RuntimeError):
    pass


def _openai_client(model: ModelConfig) -> AsyncOpenAI:
    if not model.api_key:
        raise LLMError(
            f"model {model.alias!r} needs {model.api_key_env} set — add it to .env"
        )
    return AsyncOpenAI(base_url=model.base_url, api_key=model.api_key)


@observe(name="llm_complete")
async def complete(
    role: str,
    messages: list[dict],
    *,
    model_alias: str | None = None,
    **kwargs,
):
    """Non-streaming completion for a role. Returns the OpenAI response object."""
    registry = get_registry()
    candidates = [registry.resolve(role, model_alias)]
    fallback = registry.fallback_for(role) if model_alias is None else None
    if fallback:
        candidates.append(fallback)

    last_error: Exception | None = None
    for model in candidates:
        client = _openai_client(model)
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await client.chat.completions.create(
                    model=model.model_id, messages=messages, **kwargs
                )
            except Exception as exc:  # 429/5xx/timeouts — backoff and retry
                last_error = exc
                wait = 2**attempt
                logger.warning(
                    "llm %s attempt %d/%d failed (%s); retrying in %ds",
                    model.alias, attempt + 1, _MAX_ATTEMPTS, exc, wait,
                )
                await asyncio.sleep(wait)
        logger.error("llm %s exhausted retries; trying fallback if any", model.alias)
    raise LLMError(f"llm role {role!r} failed after retries: {last_error}")


# ---------------------------------------------------------------------------
# Embeddings — BGE-M3 local (spec/06), batched async (v1 embedder pattern)
# ---------------------------------------------------------------------------

_bge_model = None
_bge_lock = asyncio.Lock()


async def _get_bge():
    global _bge_model
    async with _bge_lock:
        if _bge_model is None:
            model_cfg = get_registry().resolve("embeddings")
            logger.info("Loading %s (first call downloads the model)…", model_cfg.model_id)

            def _load():
                from FlagEmbedding import BGEM3FlagModel

                return BGEM3FlagModel(model_cfg.model_id, use_fp16=True)

            _bge_model = await asyncio.get_running_loop().run_in_executor(None, _load)
    return _bge_model


def _fake_embedding(text: str, dim: int) -> list[float]:
    """Deterministic, finite, L2-normalized pseudo-embedding for tests
    (EMBEDDINGS_FAKE=1). Bytes → [-1, 1] floats (never NaN/inf)."""
    raw: list[float] = []
    counter = 0
    while len(raw) < dim:
        h = hashlib.sha256(f"{text}:{counter}".encode()).digest()
        raw.extend((b - 127.5) / 127.5 for b in h)
        counter += 1
    raw = raw[:dim]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / norm for x in raw]


@observe(name="embed_texts")
async def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model_cfg = get_registry().resolve("embeddings")
    dim = model_cfg.dim or 1024

    # keep indices aligned for empty inputs
    safe_texts = [t if t and t.strip() else " " for t in texts]

    if get_settings().embeddings_fake:
        return [_fake_embedding(t, dim) for t in safe_texts]

    if model_cfg.provider == "openai_compat":
        return await _embed_openai_compat(model_cfg, safe_texts, dim)
    if model_cfg.provider == "local_embeddings":
        return await _embed_bge(safe_texts)
    raise LLMError(f"embeddings provider {model_cfg.provider!r} not supported")


async def _embed_openai_compat(
    model_cfg: ModelConfig, texts: list[str], dim: int
) -> list[list[float]]:
    """Hosted embeddings via the OpenAI-compatible endpoint (e.g. Gemini's
    gemini-embedding-001). `dimensions` truncates to the schema's vector size."""
    client = _openai_client(model_cfg)
    out: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[start : start + _EMBED_BATCH_SIZE]
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await client.embeddings.create(
                    model=model_cfg.model_id, input=batch, dimensions=dim
                )
                # data is returned in input order; some compat layers (Gemini)
                # leave `index` null, so don't rely on it for ordering.
                out.extend(d.embedding for d in resp.data)
                break
            except Exception as exc:  # 429/5xx/timeouts — backoff and retry
                last_error = exc
                wait = 2**attempt
                logger.warning(
                    "embed batch [%d:%d] failed (%s); retrying in %ds",
                    start, start + len(batch), exc, wait,
                )
                await asyncio.sleep(wait)
        else:
            raise LLMError(f"embeddings failed after retries: {last_error}")
    return out


async def _embed_bge(texts: list[str]) -> list[list[float]]:
    """Local BGE-M3 (provider=local_embeddings). Requires the FlagEmbedding extra."""
    model = await _get_bge()
    loop = asyncio.get_running_loop()
    all_vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[start : start + _EMBED_BATCH_SIZE]

        def _encode(b=batch):
            result = model.encode(b, batch_size=len(b), max_length=8192)
            return [v.tolist() for v in result["dense_vecs"]]

        all_vectors.extend(await loop.run_in_executor(None, _encode))
    return all_vectors
