# Tech Stack & Deployment

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js + React, Tailwind, shadcn/ui, PDF.js | Minimal, responsive. Visualizer ported from v1. |
| Backend | **FastAPI** (Python) | One language across backend + AI service. JWT auth (lib or Supabase Auth — open decision). |
| AI service | FastAPI + `sse-starlette`, Pydantic, `openai` SDK, SQLAlchemy + asyncpg, pgvector | No LangChain / LangGraph / LlamaIndex. |
| Jobs | **arq** (Redis-based, async) | Ingestion queue + background runs. Note: Redis alone is only the broker — arq is the ~1-file library supplying workers, retries/backoff, timeouts, job status, scheduling, graceful shutdown. Not extra infra (pip package); without it we'd hand-roll the same logic around BLPOP. Celery only if we outgrow arq. |
| DB | Postgres 16 + pgvector | One schema, hard FKs. |
| Cache/queue | Redis | arq broker + run-state cache + pub/sub for background-run events. |
| Object storage | **AWS S3 + CloudFront** (prod); MinIO or a dev bucket (dev) | Original PDFs + extracted images. CloudFront neutralizes S3 egress cost (1 TB/mo free tier) and edge-caches PDFs for the visualizer; CloudFront signed URLs for access control. |
| Errors | **GlitchTip** (or Bugsink) — self-hosted, Sentry-SDK-compatible | Services use standard `sentry-sdk`, DSN points at our instance; swappable to hosted Sentry by env var. Covers exceptions across all services (distinct from LLM tracing). |
| LLM observability | **Langfuse, self-hosted, from day one** | Instrumented at the `llm.py` abstraction layer (see 06): every call traced with role/alias/provider/latency/tokens/cost → provider & model comparisons in dashboards. `agent_run_events` remains the product-level run trace (replay, reconnect); Langfuse is the model-level lens. |

## Evals (non-negotiable, day one)

A citation-first product without evals regresses silently. From Phase 1:

- 30–50 real questions against known documents (first vertical's material), each with
  expected evidence (doc + section) and expected behavior (answer / clarify / abstain /
  refuse-out-of-scope).
- Metrics: evidence recall, citation precision, unsupported-claim rate, tool-call validity
  rate, abstention correctness, latency, cost per answer.
- Run on every retrieval/prompt/model change; this is also the model-bench harness.

## Repo layout (monorepo)

```
relearn-new/
  spec/            ← these documents
  frontend/        Next.js
  backend/         FastAPI gateway
  ai/              FastAPI agent runtime + arq ingestion worker (one package, two processes)
  packages/shared/ event types, SSE protocol constants, citation contract types
  docker-compose.yml
  evals/
```

## Local dev environment — dev container (zero host dependencies)

The host machine installs only **Docker Desktop and git** (an editor like Cursor is
optional). Everything else lives in containers; deleting them leaves the laptop clean.

- A **dev container** service (Python 3.12 + uv, Node + pnpm, Claude Code CLI
  pre-installed) in the dev compose file, alongside postgres, redis, minio. App
  processes (uvicorn, arq, `next dev`) run inside it — no docker-socket access needed.
- **Editor-agnostic workflow** (no VS Code required):
  `docker compose up -d` → `docker compose exec dev zsh` → run `claude` inside.
  `~/.claude` persists on a named volume (login once); app ports (3000/8000) mapped to
  the host so the browser works normally.
- The repo folder is the **only** host mount (code stays on the host for git safety;
  all dependencies live in container volumes). Because it's a bind mount, Cursor on the
  host edits the same files for free. Rule: **humans may edit from the host; agents and
  all command execution stay inside the container** (Cursor's agent, if used, must
  attach via its Dev Containers support, not run on the host).
- **Safe for unattended/allow-all Claude Code** (Anthropic's intended pattern): Claude
  runs inside the dev container — it cannot see anything outside the repo mount or
  modify the host OS. Worst case: rebuild a container, re-checkout code, re-run
  migrations; the S3 parse cache makes even data loss free.
- **Scoped credentials only**: an IAM user restricted to the single S3 bucket; model API
  keys with spending caps; never mount `~/.aws`/`~/.ssh`. Push to GitHub often (pushed
  history is outside the blast radius).
- Optional hardening later: egress allowlist firewall (Anthropic's reference
  devcontainer pattern); non-root container user from day one.

## Deployment

**Dev** — the devcontainer compose stack above: postgres(+pgvector), redis, minio,
**langfuse**, **glitchtip**, dev container (backend, ai, worker, `next dev` run within).
Models via `models.yaml` + provider keys. Marker via Datalab API key.

**Prod v1 (first users) — all-AWS, one box** — a single EC2 instance (~t3.xlarge,
region `ap-south-1` Mumbai) running the same docker-compose as dev (backend, ai, worker,
Postgres, Redis, Langfuse, GlitchTip) behind Caddy/Traefik; **S3 + CloudFront** for
files. Datalab API for parsing, hosted providers for models. **No EKS/ECS/ElastiCache/
Lambda yet** — managed AWS pieces are adopted on signal, not ambition. Nightly Postgres
dumps to S3 from day one. Apply for **AWS Activate credits before spending** (student/
founder programs apply too).

**Prod v2 (first institute)** — Postgres → **RDS** (pgvector supported; the question
bank is now someone's asset — PITR matters). Services → ECS Fargate and Redis →
ElastiCache only when the single box is actually strained. GPU for self-hosted
vLLM/Marker: `g5.xlarge` on credits is convenient; Lambda Labs/RunPod is markedly
cheaper once credits run out — revisit then. Agent model stays API until volume flips
the economics.

**Security baseline (v1)** — backend-only public exposure; internal token between
backend↔AI service; per-space scoping enforced in SQL on every tool; rate limiting at the
gateway; signed URLs for PDFs; audit trail via `agent_run_events`.
