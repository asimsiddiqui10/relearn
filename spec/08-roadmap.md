# Roadmap

Sequenced by dependency. Student side first; institute side designed-for but built later.

## MVP — Student side

### Phase 0 — Foundation (port, don't invent) · ~weeks 1–2
- Monorepo scaffold; docker-compose; Postgres schema (02) migrated.
- Ingestion worker ported from `mvp/v1`: Marker client, normalize_tree, tree_mapper,
  embedder (swap to BGE-M3), quality gates added.
- Auth + personal space; upload → ingest → resource ready.
- PDF visualizer ported; document structure browsable.
- **No new ideas in this phase — only porting.**

### Phase 1 — Agentic core (the MVP demo) · ~weeks 2–4
- Agent loop + retrieval tools (search_chunks, get_toc, read_section, expand_chunk,
  get_images) + evidence registry + citation contract.
- Full SSE streaming with live step timeline (04) — thinking, tool activity, deltas.
- Multi-document Q&A within a space; syllabus-locked refusal outside scope.
- `ask_user` clarification (HITL suspend/resume mechanism built here).
- Citation click → PDF highlight, end to end.
- Eval set v1 (30–50 questions); model bench (Kimi K2 vs Qwen3-235B vs GLM-4.6); lock
  primary model.
- **Demo**: upload coaching material, ask a cross-document question, watch the agent
  search, get a cited answer, click into the PDF.

### Phase 2 — Trust layer · ~weeks 4–6
- Abstention behavior ("evidence is weak; here's what's missing").
- Contradiction surfacing, prompt-level: sources disagree → both cited, uncertainty stated.
- Post-generation citation verification pass; `uncited` flags surfaced in UI.
- Confidence indicator (heuristic: retrieval scores, evidence density, cross-source
  agreement).
- Feedback capture wired: thumbs + flag-citation on every evidence block → `feedback`.

### Phase 3 — Questions v1 · ~weeks 6–9
- Question-paper ingestion mode (05): per-question chunking, Pattern A/B, subject
  sections, LaTeX preserved, answer-key matching; bulk PYQ upload.
- Question bank: filterable repository (topic/subject/year/source/difficulty), scoped to
  user/space.
- `query_question_bank` tool — "show me all PYQs on rotational motion across my resources."
- Generate-questions-from-section, pulling stylistic priors from the bank;
  `save_questions` behind an approval gate.
- Generated answers/solutions always `provenance='generated'` + confidence.

### Phase 4 — Sharing & workflows · ~weeks 9–12
- Space membership, invites, roles enforced; shared resources; per-user private chats
  (optionally public to space).
- Space instructions (agent guidance) + space memory (comments/changelog).
- Mike-style workflows: `workflows` table + `read_workflow` tool + CRUD/share UI.
- "Share your agentic RAG" demoable: invite a friend into a configured space.

**MVP definition of done**: a student can upload everything they study from, ask anything
within it, trust and verify every answer visually, build a question bank from PYQs,
generate practice questions, and share the whole setup with their study group.

## Explicitly cut from MVP
Plan mode, concept graph, mind maps, memory/behavior learning, annotations, practice-
session analytics, coverage view, multi-language, web links, handwritten notes (vision),
flashcards, and all institute UI.

## Institute side (kept in schema, built post-MVP)
Batches/sections (space variant + content push), bulk onboarding/invites, **DPP generator**
(chapter → 10–20 problems → in-app + institute-format PDF; likeliest deal-closer),
**test series generation** (format ingestion, agentic selection across topics/difficulty/
marks, validation, editable output — largest surface, intentionally last), class/test
schedulers + timetables, doubt rooms, leaderboards, notifications, parent dashboards,
WhatsApp integration, white-labelling, content-control/IP protection, OMR/answer checking,
live sessions, AI teaching assistant, analytics dashboards.

## Spec'd for post-MVP (see 10-background-runs-and-workflows.md)
- **Background run mode** (arq-executed agent loop, checkpoint-per-tool-call,
  reconnect-replay) — prerequisite for the two workflows below; small lift once HITL
  suspend/resume exists.
- **W1 Notes Maker** — cited notes across all space resources, `write_artifact` tool,
  PDF/DOCX export.
- **W2 Coverage / Provenance** — question-paper → source-section mapping with
  exact/conceptual/partial/unsupported classification + coverage report; resource-vs-
  resource comparison.

## Future features — student, post-MVP (rough order)
1. **Practice sessions** + post-session analysis (accuracy by topic, time per question,
   weak areas, next-session suggestions).
2. **Syllabus/topic mapping** first-class (user-provided or auto-generated) → unlocks
   coverage comparison (papers vs material), weak-topic detection, practice targeting.
3. **Coverage view** (NeetCode-style done/not-done per section) + weak-topic detection
   from feedback/query logs.
4. **Fast path** for simple queries (cost: single-search one-shot answers, no loop) —
   built from traffic data.
5. **Claim-level verification** (every claim ↦ evidence chunk via NLI or guided check)
   + citation quality metrics (precision/recall, unsupported-claim rate, page-link
   success rate).
6. **Plan mode** (RAG + concept graph + LLM planner; prerequisite edges, per-step sources
   and practice items) — big, explicitly later.
7. **Contradiction analysis** as a dedicated cross-document feature.
8. Annotations/collaborative highlights (PDF.js overlay; text-fingerprint anchoring for
   re-upload stability), revision/mind-map agent, cited flashcards, study-session mode,
   student memory/behavior learning, multimodal ingestion (DOCX/PPT/YouTube/recordings),
   handwritten notes (Qwen2.5-VL path), multi-language + simplification, links/web
   support, progress dashboards, markings, predicted papers, notes-maker, mobile app,
   public space templates/discovery.
