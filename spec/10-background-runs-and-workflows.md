# Background Runs & Long-Running Workflows

Long-running, task-completing agents (notes generation, coverage analysis, provenance
reports) without LangChain/LangGraph. Durable execution is a **background-job problem**,
not a framework problem — every piece already exists in this architecture (persisted run
state, `agent_run_events`, arq workers, Redis).

Note: MikeOSS does **not** implement this — its loop is request-scoped (max 10
iterations, dies with the HTTP connection). This is our extension.

## Run modes

| Mode | Executor | Lifetime | Use |
|---|---|---|---|
| `interactive` | request handler | one SSE request (HITL suspends allowed) | normal chat |
| `background` | arq worker | survives disconnects, hours if needed | notes maker, coverage analysis, test generation (later) |

Same loop code in both modes — only the executor and checkpoint frequency differ.

## Background execution

```
POST /runs {mode: background, workflow_id?, input}
  → agent_runs row (status=queued) → arq enqueue → 202 + run_id

worker:
  load run → run the loop
  every event  → append agent_run_events (seq)   [already in spec 04]
               → publish Redis pub/sub run:{id}
  after EVERY tool call → checkpoint state_json   (interactive runs only
                                                   checkpoint at HITL suspends)
  finish → status=completed, artifact links, notification

client:
  GET /runs/{id}/events (SSE, via backend)
  → replay history from agent_run_events, then tail live via pub/sub
  → tab closed? run continues; reopen = full replay (same block renderer as chat)
```

Crash recovery: worker dies → arq retries → loop resumes from last checkpoint.
HITL still works in background mode: `approval_required` event → run suspends →
user responds whenever → resume re-enqueues.

## "All tasks complete before the agent terminates"

Two patterns; pick per job. Rule of thumb: **agent loop for judgment, code loop for
volume.** A background run can contain both.

### A. Agent-managed task list (open-ended jobs)
New tool `task_list` (`create_tasks`, `complete_task`, `list_tasks`); tasks stored in
`run_tasks` (run_id, seq, title, status). **Enforcement lives in loop code, not model
goodwill**: finalize refuses to end the run while tasks are open and injects
"N open tasks remain: …" back into the conversation (bounded retries, then fail with
report). Tasks emit `task_update` events → frontend renders a live checklist
(Claude Code TODO pattern).

### B. Deterministic orchestration + agentic fallback (batch jobs)
Code loops over a known work-list; each item gets cheap deterministic processing
(retrieval + structured-output classification); the agent is invoked **only as fallback**
for hard items. Checkpoint = items done. Parallelizable, cheap, resumable.

## Built-in workflows (system rows in `workflows`)

### W1 — Notes Maker (build later; spec'd now)
Combine every resource in a space into downloadable, cited notes.
- Workflow prompt: walk each resource's TOC; per major topic, read sections, **merge
  overlapping content across sources**, write cited notes; track sections via task list.
- New tool **`write_artifact(artifact_id, section_md)`** — appends cited markdown to an
  `artifacts` row. The artifact is external memory: full notes never need to fit in one
  context window.
- Pattern A (task list) over the TOC union; background mode.
- Export: backend renders artifact md → PDF/DOCX (citations as source+page refs);
  download from chat and the space's artifacts list.

### W2 — Coverage / Provenance Analysis (build later; spec'd now)
Two shapes, one skeleton:
- **Question-paper provenance**: paper (already ingested via question-paper mode) +
  source docs → Pattern B code loop per question: hybrid retrieval (per-question-type
  strategy: factual→lexical-heavy, conceptual→semantic-heavy, MCQ→stem+options terms,
  assertion-reason→decomposed subclaims) → structured classification
  `exact / conceptual / partial / unsupported` + evidence chunks → store
  `question_source_mappings` → aggregate per-section coverage stats → cited report
  artifact (which sections are over-tested / under-represented / untested). Agentic
  fallback only for OCR-garbled or diagram questions.
- **Resource-vs-resource comparison** ("compare photosynthesis @file1 @file2"): topic
  union from both TOCs → per-topic retrieve from each → compare/contrast with citations
  from both sides → report artifact. Contradictions explicitly surfaced with both
  citations.

## Schema additions

- **artifacts** — id, space_id, run_id, type (`notes` / `report`), title, content_md,
  citations_json, status, created_at
- **run_tasks** — run_id, seq, title, status (`open` / `done` / `failed`)
- **question_source_mappings** — question_id, classification, evidence chunk_ids,
  confidence, run_id
- **agent_runs** gains: mode (`interactive` / `background`), workflow_id?, artifact_id?
- New events (04): `task_update`, `artifact_updated`, `run_progress {done,total}`

## Frontend (MikeOSS note)

Mike's frontend patterns (chat layout, streaming blocks, working-state UX) are worth
replicating — **as patterns, not code: MikeOSS is AGPL-3.0**; copying source would force
Relearn to AGPL. Re-implement in our own Next.js/Tailwind/shadcn components. Mike has no
PDF visualizer (its doc view is a Tiptap editor) — the bbox-overlay visualizer is ours
alone: keep v1's two correct ideas (raw Marker coordinates; stretch-fit SVG overlay) and
rebuild the component cleanly with explicit load/render/highlight states, tested against
fixed sample PDFs.
