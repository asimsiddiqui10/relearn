# Relearn — Product Overview

> **Spec status: FINAL — ready to build.** All decisions closed (see 09). The only
> code inputs to this build are this spec and `reference/v1/` (salvaged heuristics,
> reference-only — never imported). The old MikeOSS and mvp/v1 repos are deletable;
> nothing is copied from them.

A citation-first **agentic** study workspace. Students upload their institute's or their own
material into Spaces, ask questions, and get answers where every claim traces to an exact
location in a source PDF, visualized live. The agent navigates documents, iterates until
coverage is complete, asks when ambiguous, and abstains when evidence is weak.

Built **student-first**, with the schema and runtime designed so the institute layer
(batches, RBAC, DPP/test generation, workflows) bolts on without re-architecture.

## Positioning

- AI Operating System for educational institutes — but the wedge is the student experience.
- "Share Context with your Study Group" — shared Spaces, shared agentic RAGs.
- Strict syllabus locking: the agent answers only from the Space's resources.
- Making students trust AI responses the way they trust a textbook.

## The three product invariants

Everything else can change; these cannot:

1. **Provenance** — every factual claim maps to evidence with chunk-level provenance
   (document, page, bbox).
2. **Scope** — the agent operates only within the Space's resources. Strict syllabus
   locking; refusal outside scope.
3. **Traceability UX** — a user can always click from a claim to the exact highlighted
   region of the source PDF.

## Why agentic (vs. the old fixed pipeline)

The v1 RAG pipeline (mvp/v1) was a fixed 5-stage flow: a one-shot planner picked tools with
no ability to look at results and retry. If retrieval missed, the answer missed. The agentic
rewrite replaces pipeline stages with model judgment + tools:

| Old pipeline stage | Agentic equivalent |
|---|---|
| Query understanding, scope routing, clarification (SCL) | Agent judgment + `ask_user` tool |
| Hybrid search + RRF + heading boost | `search_chunks` tool (same SQL internals, kept verbatim) |
| Structure-guided retrieval, hierarchy expansion | `get_toc`, `read_section`, `expand_chunk` tools |
| Coverage planning | Agent behavior: sees the TOC, notices gaps, searches again |
| Evidence packs, grounded synthesis, citations | **Hard contract, unchanged** — evidence registry + `[E#]` tags |

What survives from v1 unchanged: Marker ingestion (normalize tree, tree mapper, raw payload
storage), the hybrid retrieval SQL, the EvidenceItem shape, the PDF visualizer
(bbox/polygon overlays in Marker coordinates).

## Document map

| File | Contents |
|---|---|
| [01-architecture.md](01-architecture.md) | Services, diagram, request flows |
| [02-data-model.md](02-data-model.md) | Postgres schema |
| [03-agent-runtime.md](03-agent-runtime.md) | Loop, tools, evidence contract, HITL |
| [04-streaming-protocol.md](04-streaming-protocol.md) | SSE events + live progress UX (Claude-Code-style) |
| [05-ingestion.md](05-ingestion.md) | Rule-first ingestion, question-paper mode |
| [06-models.md](06-models.md) | Open-source model choices, hosting strategy |
| [07-stack-deployment.md](07-stack-deployment.md) | Tech stack, dev/prod deployment |
| [08-roadmap.md](08-roadmap.md) | MVP phases, institute side, future features |
| [09-decisions.md](09-decisions.md) | Final decision record — every architectural choice, settled, with reasons |
| [10-background-runs-and-workflows.md](10-background-runs-and-workflows.md) | Durable long-running agents, task lists, notes-maker & coverage workflows |
| [11-frontend.md](11-frontend.md) | Frontend stack (Mike-pattern), component inventory, block renderer, visualizer, responsive |
