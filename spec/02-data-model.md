# Data Model

One Postgres schema (+ pgvector). Hard FKs everywhere. RBAC fields exist from day 1 even
though the admin UI ships later.

## Identity & workspace

- **users** — id, email, name, auth fields, created_at
- **spaces** — id, owner_user_id, name, description, instructions (space-level agent
  guidance), memory (text field: comments/remarks/tasks/changelog), settings_json
- **space_members** — space_id, user_id, role (`owner` / `admin` / `member`), invited_by,
  joined_at. Unique (space_id, user_id).
- **resources** — id, space_id, type (`document` / `link` / `note` / `plan`),
  title, visibility, uploaded_by, document_id (FK, nullable for non-document types),
  status (`pending` / `ingesting` / `ready` / `failed`), created_at

## Document corpus (written by AI service)

- **documents** — id, space_id, file_path (S3 key `pdfs/{sha256}.pdf`), checksum —
  **UNIQUE (space_id, checksum)**: re-upload within a space short-circuits to the
  existing document. Documents are owned by their space (no cross-space sharing for
  now; the global S3 parse cache — see 05 — already makes a future migration to shared
  documents free). doc_type
  (`textbook` / `notes` / `question_paper` / `slides`), status, summary,
  summary_token_count, metadata_json (incl. `page_dimensions` for the visualizer)
- **structure_nodes** — id, document_id, parent_node_id, depth, heading_level,
  heading_text, node_type, structure_path (e.g. `1/2.3/4`), heading_breadcrumb,
  page_start, page_end, subtree_chunk_count, subtree_token_count, summary,
  normalization_flags, marker_block_id
- **chunks** — id, document_id, structure_node_id, chunk_type (`text` / `caption` /
  `question` / `equation` / `table`), content, content_html, page_number, bbox, polygon
  (Marker coordinate space, stored raw), token_count, structure_path, heading_breadcrumb,
  attached_image_id, marker_block_id, embedding `vector(1024)` (BGE-M3), tsv (full-text)
  - Indexes: HNSW on embedding, GIN on tsv, (document_id, page_number), (structure_node_id)
- **images** — id, document_id, structure_node_id, page_number, bbox, file_path,
  caption, caption_embedding (optional), figure_ref_norm (e.g. `figure_2_1`)
  - Index: (document_id, figure_ref_norm) — instant figure-reference lookup
- **marker_ingest_runs** — document_id, raw_payload, normalized_tree, marker_version,
  created_at. Enables offline reprocessing without re-calling the Marker API.
- **ingest_jobs** — id, resource_id, status, stage, error, attempts, timestamps

## Questions module

- **syllabus_topics** — id, space_id, subject, parent_topic_id, name, ordering.
  (Table exists day 1; populated/used from Phase 3+.)
- **questions** — id, space_id, source_document_id (nullable — generated questions have
  none), question_text, question_html, options_json, answer, solution, marks,
  difficulty, subject, exam_name, year, page_number, bbox, question_number,
  has_diagram, embedding, provenance (`ingested` / `generated`), confidence
- **question_topics** — question_id, topic_id (many-to-many)

## Chat & agent

- **chat_sessions** — id, space_id, user_id, title, visibility (`private` / `space`),
  **summary** (rolling compaction of older turns, incl. key `[E#]→chunk_id` mappings —
  see 03 Conversation memory), summary_token_count, created_at. Private by default.
- **chat_messages** — id, session_id, role, content, citations_json, created_at
- **agent_runs** — id, session_id, **mode (`interactive` / `background`)**, workflow_id
  (nullable), artifact_id (nullable), status (`queued` / `running` / `suspended` /
  `completed` / `failed`), state_json (messages + registry snapshot for suspend/resume +
  background checkpoints), model, token_usage, started_at, finished_at
- **agent_run_events** — run_id, seq, event_type, payload_json, created_at.
  Append-only trace of every SSE event. Powers reconnect-replay, debugging, and analytics.
- **evidence_log** — run_id, eid, chunk_id, document_id, page, bbox — what was cited where
- **feedback** — id, user_id, message_id, chunk_id (nullable), signal (`helpful` /
  `not_helpful` / `flag_citation`), note, created_at. Substrate for weak-topic detection
  and human-review scoring later.

## Workflows & background runs (Phase 4+ / spec 10)

- **workflows** — id, owner_user_id, space_id (nullable = personal), title, prompt_md,
  is_system, created_at
- **workflow_shares** — workflow_id, user_id/email, access (`read` / `write`)
- **artifacts** — id, space_id, run_id, type (`notes` / `report`), title, content_md,
  citations_json, status, created_at
- **run_tasks** — run_id, seq, title, status (`open` / `done` / `failed`)
- **question_source_mappings** — question_id, classification (`exact` / `conceptual` /
  `partial` / `unsupported`), evidence chunk_ids, confidence, run_id

## Write-ownership convention

| Writer | Tables |
|---|---|
| Backend | users, spaces, space_members, resources, chat_sessions, chat_messages (user msgs), feedback, workflows |
| AI service | documents, structure_nodes, chunks, images, marker_ingest_runs, ingest_jobs (status), questions, agent_runs, agent_run_events, evidence_log, chat_messages (assistant msgs) |

Both read everything. Constraints are enforced by the DB, not by service discipline.
