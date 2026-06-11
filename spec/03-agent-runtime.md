# Agent Runtime

No framework. One loop, ~200 lines, fully ours. OpenAI-compatible client (`openai` SDK
with `base_url`) so any OSS model/provider plugs in.

## The loop

```python
async def run_agent(run: AgentRun) -> AsyncIterator[Event]:
    messages = [system_prompt(run.space), *history(run.session), user_message]
    for iteration in range(MAX_ITERATIONS):          # ≈15
        async for delta in llm.stream(messages, tools=TOOL_SCHEMAS):
            yield delta_event(delta)                  # thinking_delta / text_delta, live
        response = collect()
        if not response.tool_calls:
            break                                     # final answer produced
        for call in response.tool_calls:
            yield tool_started(call)                  # deterministic label, see 04
            if TOOLS[call.name].requires_user:        # ask_user, save_questions, ...
                persist_state(run, messages)
                yield suspension_event(call)          # clarification/approval_required
                return                                # loop SUSPENDS here
            result = await TOOLS[call.name].execute(call.args, ctx=run.ctx)
            register_evidence(run, result)            # evidence registry grows
            yield tool_result(call, result.summary)
            messages.append(tool_message(call, result.payload))
    yield from finalize(run, response)                # citation check, confidence, done
```

**Resume**: `POST /runs/{id}/resume {response}` loads `state_json`, appends the user's
answer/approval as the pending tool's result, and re-enters the loop. One mechanism =
clarification + approval + (later) long-running agents.

**Iteration cap** at ~15; on hitting it, the agent is instructed to answer with what it
has and state what's missing.

## Tools (v1 set)

All tool schemas are Pydantic models (JSON schema auto-generated). Every tool that touches
the corpus receives the run context (`space_id`, allowed `resource_ids`) server-side —
scope is enforced in SQL, never trusted to the model.

| Tool | Signature (essentials) | Behavior |
|---|---|---|
| `search_chunks` | query, doc_ids?, top_k | Hybrid semantic (pgvector) + lexical (tsv), RRF fusion k=60, heading-match boost. v1 SQL kept verbatim. |
| `get_toc` | doc_id | Structure-node tree with per-section chunk/token counts. How the agent judges scope and coverage. |
| `read_section` | node_id | All chunks under a node, capped (~4k tokens); falls back to the node summary + child list when oversized. |
| `expand_chunk` | chunk_id | Prev/next neighbors + parent heading context (late expansion). |
| `get_images` | doc_id?, query? \| figure_ref? | figure_ref → indexed `figure_ref_norm` lookup; query → caption-embedding search. |
| `ask_user` | question, options? | **Suspends.** Clarification only when ambiguity blocks correctness (SCL as a tool, with prompt guidance to prefer answering). |
| `read_workflow` | workflow_id | Returns stored prompt template (Phase 4). |
| `query_question_bank` | filters (topic, subject, year, source, difficulty) | Bank search; questions are evidence too. |
| `save_questions` | questions[] | **requires_approval** — suspends with a preview card; commits on approval. |

Local slugs in model context (`doc-0`, `doc-1` — Mike's pattern), mapped server-side to
UUIDs. The model never sees raw IDs.

## Evidence contract (the product core)

Every retrieval tool returns evidence items registered in the run's registry:

```python
EvidenceItem:
    eid: str              # "E1", "E2" — short, token-cheap
    chunk_id, document_id
    page: int
    bbox / polygon        # Marker coordinates
    heading_breadcrumb: str
    text: str
```

Rules enforced by the system prompt and verified post-generation:
- Factual content must cite `[E#]`. Citations attach to explanation units/sentences, not
  every word.
- The model may merge evidence from multiple sources into one unit and add connecting
  language; it must not add unsupported facts.
- **Abstention**: weak evidence → say so, state what's missing, optionally ask a narrowing
  question. Out of space scope → refuse (syllabus locking).
- **Contradiction**: when sources disagree → present both with citations, state the
  disagreement explicitly.

**Post-generation verification (v1, cheap)**: parse `[E#]` tags → every tag resolves in the
registry, else strip + flag; factual-looking paragraphs with zero citations get flagged
`uncited` in the `citation_map` event. (Claim-level NLI verification is a later layer —
see roadmap.)

**Confidence** (v1, heuristic): derived from retrieval scores, evidence density, and
agreement across sources — surfaced as low/medium/high with a reason, not a fake number.

## Failure handling & retries

One consolidated policy; each layer owns its own failures:

| Layer | Failure | Handling |
|---|---|---|
| LLM call (`llm.py`) | 429 / 5xx / timeout | Exponential backoff, ~3 attempts; then **fallback model alias** for the role (configured in models.yaml); then run-level error. All retries traced in Langfuse. |
| Structured output | Schema-invalid (provider ignored response_format) | Pydantic parse fails → Instructor-style retry with validation error fed back (max 2); then error. |
| Tool execution | Tool raises / times out | **Returned to the model as an error tool-result, never a crash** — the agent adapts: retries with different args, uses another tool, or tells the user. Two consecutive failures of the same tool+args → loop injects "stop retrying this; work around it." |
| Run level | Iteration cap, unrecoverable error | `error` event with reason; partial answer + what's missing when possible. Interactive: user retries. Background: arq retry resumes from last checkpoint. |
| Ingestion | Stage failure | arq retry w/ backoff (attempts in `ingest_jobs`); quality-gate failure → repair path → `failed` with human-readable reason. |
| Stream | Disconnect | Reconnect with `last_seq` → replay from `agent_run_events` (04). Interactive runs keep executing server-side for a grace period (~60s) before suspending. |

## Conversation memory

**Within a session (MVP)** — rolling compaction, our own (no framework):
- Recent N turns verbatim; older turns compacted into a rolling summary stored on
  `chat_sessions.summary` (small model, updated async after each turn once the session
  outgrows a token budget).
- Context assembly: system prompt → space context → session summary → recent turns.
- Citations survive compaction by reference: the summary keeps `[E#]→chunk_id` mappings
  of load-bearing evidence so follow-ups ("explain that diagram again") can re-resolve.

**Across sessions (MVP, modest)**:
- Space memory (`spaces.memory`) + space instructions are always in the system prompt —
  durable, user-visible, user-editable memory. This is the primary cross-session channel.
- The system prompt lists titles + one-line summaries of the user's recent sessions in
  this space, so the agent knows what was previously discussed and can say "we covered
  this on Tuesday — want a recap?".

**Post-MVP**: `search_past_chats` tool (semantic search over session summaries/messages),
user-level memory (learning style, weak topics — feeds from the feedback loop), member
profiles in shared spaces.

## System prompt skeleton

1. Role + the three invariants (provenance, scope, traceability).
2. Space context: instructions, memory, resource list with slugs + one-line summaries.
3. Tool-use strategy: peek at TOC for broad questions; search before reading; check
   coverage against the TOC before answering broad questions; iterate on misses;
   clarify only when blocked.
4. Citation rules (above) + output style (headings only when they help; idea-flow
   organization; merge related evidence into coherent units).
5. Abstention + contradiction + refusal-out-of-scope behavior.
