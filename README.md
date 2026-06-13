# Relearn

Citation-first agentic study workspace. See `spec/` — the build's single source of truth.

## Layout

```
spec/            the spec (final)
reference/v1/    salvaged v1 heuristics — reference only, never imported
packages/db/     shared Postgres schema (SQLAlchemy models + Alembic migrations)
ai/              AI service: agent runtime + arq ingestion worker (Python/FastAPI)
backend/         gateway: auth, spaces, resources, upload, SSE proxy (Python/FastAPI)
frontend/        Next.js app
evals/           eval set + harness (Phase 1)
```

## Dev setup

Requirements: Docker Desktop, uv, pnpm.

```bash
cp .env.example .env          # fill in DATALAB_API_KEY / model keys as needed
docker compose up -d           # postgres(+pgvector), redis, minio
uv sync --all-packages
(cd packages/db && uv run alembic upgrade head)
```

## Status

**Phase 0 (foundation) — complete, verified end-to-end.** signup → personal
space → PDF upload → sha256 → S3 → arq worker (dedup, Marker-tree normalize, map,
embed, quality gates, transactional commit) → resource ready → structure tree +
presigned PDF for the visualizer.

**Phase 1 (agentic core) — built and tested with a scripted model.** Hybrid
retrieval (pgvector + tsv, RRF, heading boost) behind tools (search_chunks,
get_toc, read_section, expand_chunk, get_images); evidence registry with stable
`[E#]` ids; the ~200-line agent loop (model → tools → results → repeat) emitting
the full SSE event taxonomy with HITL suspend/resume; AI `/chat` SSE endpoint +
backend proxy persisting runs/events/answers; chat UI with the streaming block
renderer and citation→PDF-highlight. 27 backend/AI tests + 5 frontend reducer
tests green.

> **To run Phase 1 live you must add a model key** (`GEMINI_API_KEY` for the free
> dev default) to `.env` and restart the AI service. Without it the loop/tools/UI
> are exercised by tests but no real model call is made.

**Not yet done in Phase 1:** eval set v1 (30–50 NEET questions) + model bench —
needs real material + a model key (spec/07).

Dev note: ingestion replays from the S3 parse cache, so no Datalab key is needed
once a doc is cached; `EMBEDDINGS_FAKE=1` skips the BGE-M3 download with
deterministic vectors for tests.

Services (Phase 0+):

```bash
(cd backend  && uv run uvicorn relearn_backend.main:app --port 8000 --reload)
(cd ai       && uv run uvicorn relearn_ai.main:app --port 8001 --reload)  # AI service (agent /chat SSE)
(cd ai       && uv run arq relearn_ai.worker.WorkerSettings)        # ingestion worker
(cd frontend && pnpm dev)                                     # http://localhost:3000
```

> Restart the AI service after any change under `ai/` — a stale process serves
> old code (and a pre-fix process won't have model keys, so the agent silently
> dies mid-stream).
