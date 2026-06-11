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

Services (Phase 0+):

```bash
(cd backend  && uv run uvicorn relearn_backend.main:app --port 8000 --reload)
(cd ai       && uv run arq relearn_ai.worker.WorkerSettings)        # ingestion worker
(cd frontend && pnpm dev)                                     # http://localhost:3000
```
