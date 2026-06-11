# Ingestion

**Philosophy: rule-first ingestion (primary), LLM-assisted recovery (secondary), quality
gates before commit.** Hard rules are the default path; the LLM is a repair/assist layer
only. The hardest-won v1 logic (Marker integration, tree normalization, tree mapper,
hybrid retrieval SQL) is preserved in **`reference/v1/`** (see its README): consult it
when implementing each piece, take the heuristics, rewrite the plumbing against the new
schema. Never import from that folder.

## Pipeline

```
upload (backend) → sha256 checksum → S3 pdfs/{sha256}.pdf → ingest_jobs enqueued
  ↓ worker
0. DEDUP      UNIQUE (space_id, checksum): re-upload within the same space →
              short-circuit to the existing document ("already ingested").
1. PARSE      cache check: S3 parses/{sha256}.json exists → skip Datalab entirely,
              replay from cache. Else call Marker (Datalab API) and write the raw
              JSON to S3 — once, kept forever.
2. NORMALIZE  marker_normalize_tree (ported): snap misaligned heading levels,
              detect synthetic roots, dedupe slide artifacts
3. MAP        marker_tree_mapper (ported): tree → structure_nodes + chunks + images
              chunks carry bbox/polygon (raw Marker coords), page, breadcrumb,
              structure_path; captions become chunk_type='caption' with image FK;
              figure refs normalized → figure_ref_norm
4. EMBED      BGE-M3, batched async → pgvector
5. GATE       quality gates before commit (below)
6. REPAIR     only on gate failure: small-LLM pass on the failing region
              (garbled headings, empty sections, broken reading order)
7. SUMMARIZE  section + document summaries (small model)
8. COMMIT     transactional; resource → ready
```

## Parse cache — never pay twice (hard rule)

The raw Marker output lives **outside the database lifecycle**: `parses/{sha256}.json`
in S3, written on first parse, never deleted. Postgres (and `marker_ingest_runs`) is
wipeable dev state; the S3 cache is the durable asset. Consequences:

- `docker compose down -v`, schema migrations, chunking experiments, re-embedding —
  all replay from the cache, costing nothing.
- The cache is global even though documents are space-owned: the same file uploaded
  into another space re-chunks/re-embeds (local, free) but never re-parses (the paid
  part). Datalab is called exactly once per unique file, ever.

Minimum Phase-1 running stack: docker-compose (postgres+pgvector, redis — wipeable),
one real S3 bucket (`pdfs/` + `parses/` — the only thing that must survive), services
running locally, Datalab + model-provider keys. Langfuse/GlitchTip are opt-in via the
no-op-without-keys pattern (ported from v1 `tracing.py`). No EC2/CloudFront needed
until real users.

## Quality gates (v1 set)

- Non-empty text ratio per page above threshold (else: scanned/encoded PDF → flag for OCR
  path).
- Heading tree sanity: no orphan depth jumps, no zero-chunk document.
- Chunk length distribution sane (catches table-explosion artifacts).
- For question papers: extracted question count > 0 and question numbers roughly
  monotonic.

Gate failure → repair attempt → re-gate → still failing → resource marked `failed` with a
human-readable reason (never silently commit garbage).

## Document-type routing

`doc_type` set by the user at upload (textbook / notes / question_paper / slides), with a
cheap classifier suggestion later. Routing decides the chunking strategy; vision-model
paths (handwritten notes, scanned papers) are post-MVP.

## Question-paper mode (Phase 3)

Separate chunking strategy when `doc_type='question_paper'` — designed against real Marker
output for two-column NEET/JEE papers:

- Walk pages; `SectionHeader` blocks containing PHYSICS / CHEMISTRY / BOTANY / ZOOLOGY (etc.)
  set the current subject tag.
- **Pattern A** (common): a `ListGroup` starting with a number pattern (`^\d+[.)]`) is a
  question; pair it with the next `ListGroup` if it's options (`^\(1\)|\(a\)`); a following
  `Picture`/`Figure` sets `has_diagram`.
- **Pattern B** (merged): one `ListGroup` containing multiple `<li>` items — split by
  `<li>`; each is a self-contained question + options. Per-question bbox unavailable →
  store block bbox; the UI scrolls to the question client-side by number.
- Two-column layouts: Marker already linearizes reading order; sort extracted questions by
  `question_number` after extraction.
- LaTeX inside `<math>` tags preserved verbatim.
- Output: one chunk per question (`chunk_type='question'`) + a row in `questions` with
  subject, page, bbox, question_number, has_diagram. Structure: flat — one node per
  subject section, questions hanging off it.
- Answer keys found in the document are matched to questions by number; missing
  answers/solutions can be generated later **with provenance='generated' and a confidence
  score** — never silently mixed with extracted ones.

## What carries over from v1 (now in `reference/v1/`, reference-only)

| v1 asset | Disposition |
|---|---|
| Marker client + raw payload storage | Port |
| `marker_normalize_tree.py` (heading heuristics) | Port; wrap with quality gates |
| `marker_tree_mapper.py` | Port; add question-paper branch |
| Embedder (batched async) | Port; swap Gemini → BGE-M3, re-embed |
| Hybrid retrieval SQL (RRF, heading boost) | Port verbatim → becomes `search_chunks` tool |
| EvidenceItem shape | Port → evidence registry contract |
| PDF visualizer | **Not ported** — clean-room rebuild (spec 11); only raw-Marker-coords + stretch-fit-SVG ideas survive |
