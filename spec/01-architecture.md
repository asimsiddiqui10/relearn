# Architecture

Three services, **one database**, backend as the only public door.

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND  (Next.js)                                          │
│  chat UI · PDF visualizer (PDF.js + bbox overlay) ·           │
│  spaces UI · upload · approval/clarification cards ·          │
│  feedback buttons · live agent-step timeline                  │
└───────────────────────────┬──────────────────────────────────┘
                            │  HTTPS + SSE (single origin)
┌───────────────────────────▼──────────────────────────────────┐
│  BACKEND  (public API / gateway)                              │
│  auth & sessions · spaces, members, roles (RBAC) ·            │
│  resources CRUD · chat session metadata · upload → S3 ·       │
│  proxies /chat SSE stream to AI service · feedback capture    │
│  — holds ZERO AI logic —                                      │
└───────────┬──────────────────────────────┬───────────────────┘
            │ internal HTTP (SSE proxied)  │
┌───────────▼──────────────────────────────▼───────────────────┐
│  AI SERVICE  (Python, internal-only, trusts backend token)    │
│                                                               │
│  ┌─ AGENT RUNTIME ────────────────────────────────────────┐  │
│  │  loop: model call → tool calls → results → repeat      │  │
│  │  tools: search_chunks · get_toc · read_section ·       │  │
│  │         expand_chunk · get_images · ask_user ·         │  │
│  │         read_workflow · query_question_bank ·          │  │
│  │         save_questions (approval-gated)                │  │
│  │  evidence registry → [E#] citations → SSE events       │  │
│  │  HITL: suspend/persist/resume (clarification+approval) │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ INGESTION WORKER (Redis + arq, separate process) ─────┐  │
│  │  Marker/Datalab → normalize tree → structure_nodes +   │  │
│  │  chunks (bbox, page, breadcrumb) + images → embed →    │  │
│  │  quality gates → LLM repair only on gate failure       │  │
│  │  question-paper mode: per-question chunking            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  llm.py → OpenAI-compatible client → vLLM / OpenRouter /     │
│           Together  (agent model + small cheap model)        │
└───────────┬───────────────────────────────────────────────── ┘
            │
┌───────────▼──────────────────────────────────────────────────┐
│  POSTGRES (+ pgvector) — ONE schema, hard FKs                │
│  REDIS — job queue + run-state cache                         │
│  S3 / R2 / MinIO — original PDFs, extracted images           │
└──────────────────────────────────────────────────────────────┘
```

## Service responsibilities

### Frontend (Next.js)
Chat with streaming block renderer (see 04), PDF visualizer ported from `mvp/v1`
(`DocumentPdfVisualizer.tsx` pattern: PDF.js canvas + SVG overlay in Marker coordinates,
`preserveAspectRatio="none"`), spaces/resources UI, upload, inline HITL cards, feedback
buttons on every evidence block.

### Backend (gateway)
- The **only** public origin. Auth in exactly one place.
- Users, spaces, members, roles, resources CRUD, chat session metadata, feedback rows.
- File upload → object storage → enqueue ingest job.
- `/chat` endpoint: authenticates, attaches `{user, space, allowed resource_ids}` context,
  forwards to AI service, pipes the SSE stream back unmodified.
- AI service trusts the backend via an internal token; it never validates end users.

### AI service (Python, internal-only)
Two halves, one codebase, separate processes:
- **Agent runtime** — the loop, tool registry, evidence registry, HITL suspend/resume,
  SSE event emission. See [03-agent-runtime.md](03-agent-runtime.md).
- **Ingestion worker** — arq queue consumer. See [05-ingestion.md](05-ingestion.md).

## Hard rules (lessons from v1)

1. **One Postgres schema, hard foreign keys.** v1's sin was soft FKs across services and
   eventual-consistency syncing (`ingest_tasks` mirroring). Both backend and AI service
   connect to the same DB. Write ownership is partitioned by convention (backend writes
   users/spaces/resources/sessions; AI service writes documents/structure/chunks/embeddings/
   runs) but constraints are real, so orphaned rows are impossible.
2. **Backend is the only public door.** No CORS sprawl, no client-held AI-service tokens.
3. **No orchestration framework.** No LangChain, LangGraph, LlamaIndex. The agent loop is
   ~200 lines of our own Python. The evidence/citation contract is the product's core and
   stays fully under our control.

## Request flows

**Upload** — frontend → backend (auth, create `resource`, upload PDF to S3, enqueue job)
→ ingestion worker → Marker parse → normalize → write structure_nodes/chunks/images +
embeddings → mark resource ready. Backend reads job status from the DB; no cross-service
sync.

**Chat** — frontend opens SSE to backend → backend authenticates and forwards to AI
service → agent loop runs, emitting events for every step (thinking, tool start/result,
text deltas, citations) → events stream through the backend to the UI → citation clicks
resolve `[E#]` → chunk → bbox → PDF highlight.

**HITL** — agent calls `ask_user` or hits a `requires_approval` tool → run state persisted,
`clarification_required`/`approval_required` event emitted, loop suspends → user responds →
backend hits the AI service resume endpoint → loop continues from saved state, appending
the user's response as the tool result. One mechanism serves clarification, approval, and
(later) long-running runs.

**Where the institute side slots in later**: same backend (roles already in schema), new
workflows/tools in the AI service (DPP generation, test series = agent runs with different
tool sets and templates), new frontend surfaces. No new services.
