# v1 Reference Code — READ THIS BEFORE USING

These files are the **only** salvage from the old Relearn MVP (`mvp/v1`), copied here so
the old repos can be deleted. They are **reference material, not source code to copy
wholesale**. The new system is a fresh build; consult these when implementing the
corresponding piece, take the hard-won logic, leave the v1 plumbing behind.

| File | What's valuable | What to ignore |
|---|---|---|
| `client.py` | Marker/Datalab API call shape, polling, raw-payload handling | v1 config/coupling |
| `marker_normalize_tree.py` | ~38KB of heading-level snapping, synthetic-root detection, slide dedup heuristics — the hardest-won code in v1. Port the heuristics. | Its integration points |
| `marker_normalize.py` | Small normalize entry helpers | — |
| `marker_tree_mapper.py` | Marker JSON tree → structure_nodes + chunks + images mapping; bbox/polygon/breadcrumb extraction | v1 ORM specifics — new schema differs (see spec/02) |
| `stage1_prefetch.py` | Hybrid retrieval SQL: pgvector semantic + tsv lexical, RRF fusion (k=60), heading-match boost — becomes the `search_chunks` tool internals | The 5-stage pipeline framing around it |
| `embedder.py` | Batched async embedding pattern | Gemini-specific bits — new system uses BGE-M3 |
| `question_extractor.py` | Early question-paper extraction logic — partial; spec/05 question-paper mode supersedes it | Most of it |
| `tracing.py` | Langfuse optional `@observe` decorator pattern (no-op without keys) — port into new `llm.py` | — |

Rules for the new build:
1. **Never import from this folder.** Code is rewritten into the new services with the
   new schema/contracts; this folder is documentation in `.py` form.
2. When a v1 heuristic looks convoluted, assume it earned its complexity against a real
   PDF — understand it before simplifying, but DO simplify the plumbing around it.
3. Delete this folder when ingestion + retrieval pass the eval set.
