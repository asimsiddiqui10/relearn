# Streaming Protocol & Live Progress UX

**Principle: the agent loop is an event emitter, not a function that returns an answer.**
Every state transition becomes an SSE event the moment it happens. The user never waits on
silence because there is no silent state. The visible steps are themselves the trust
mechanism — a student who watched the agent search their own syllabus believes the
citation.

## Transport

- AI service: FastAPI + `sse-starlette` `EventSourceResponse`; the loop is an async
  generator yielding events.
- Backend: proxies the stream with `httpx` streaming — pipe-through, no buffering.
- Frontend: `fetch()` + ReadableStream SSE parser (not `EventSource` — it can't POST).
- Every event carries a monotonic `seq`. Reconnect: client sends `last_seq`; server
  replays the gap from `agent_run_events` (the append-only trace), then continues live.
- `heartbeat` every ~15s keeps proxies from killing idle connections during long tool
  calls.

## Event taxonomy

| Event | Payload | UI effect |
|---|---|---|
| `run_started` | run_id, model | message shell appears |
| `thinking_delta` | text | collapsed "Thinking…" block, live shimmer, expandable (models exposing `reasoning_content`: Kimi K2, Qwen3) |
| `text_delta` | text | answer streams into the current text block |
| `tool_started` | tool, **label**, args_summary | tool block appears with spinner: "Searching 'photosynthesis' in *Biology Module 2*…" |
| `tool_result` | tool, **summary**, duration_ms | same block flips in place to ✓ + "Found 12 passages across 3 sections" + duration |
| `evidence_added` | eid, chunk_id, doc, page, bbox | citation registry grows; UI can pre-warm PDF highlights |
| `clarification_required` | question, options? | inline question card; input focused |
| `approval_required` | tool, preview (e.g. questions to save) | inline approval card with Approve / Reject |
| `citation_map` | { E# → {chunk_id, page, bbox, flags} } | citations become clickable; `uncited` flags rendered |
| `confidence` | level, reason | confidence chip on the answer |
| `run_completed` | usage, duration | timeline collapses to "Worked for 14s · 5 steps" |
| `error` | message, recoverable? | error block + retry affordance |
| `heartbeat` | — | none |

## Deterministic labels — no LLM in the narration path

Each tool defines two pure functions:

```python
class SearchChunks(Tool):
    def label(self, args) -> str:
        scope = doc_titles(args.doc_ids) or "all resources"
        return f'Searching "{args.query}" in {scope}…'
    def summarize(self, result) -> str:
        return f"Found {len(result.chunks)} passages across {result.section_count} sections"
```

Zero latency, zero cost, always accurate — the Claude Code approach. Examples:
`get_toc` → "Reading the table of contents of *NCERT Physics XI*";
`query_question_bank` → "Searching question bank: rotational motion, 2019–2023" →
"Found 8 questions from 4 papers".

## Ordering guarantee (Mike's flushText pattern)

Text deltas are buffered and **flushed before** emitting `tool_started`, so events always
arrive in true chronological order — the UI never shows a tool running before the text
that preceded it.

## Persistence

Every emitted event is also appended to `agent_run_events` (run_id, seq, type, payload).
One table powers: reconnect-replay, full run debugging/replay, latency analytics, and
later session-feedback features. Free because emission and persistence share one code
path.

## Frontend rendering model

The assistant message is an **ordered list of blocks** built by a reducer over the event
stream:

```
[ ThinkingBlock    (collapsed, expandable, live while streaming)   ]
[ ToolBlock        spinner+label → ✓ +summary+duration, in place   ]
[ ToolBlock        ...stack of these = the visible agent timeline  ]
[ TextBlock        streaming markdown, [E#] → citation chips       ]
[ HITLBlock        clarification question / approval card, inline  ]
[ TextBlock        ... (text may resume after tools/HITL)          ]
```

Reducer rules:
- `tool_started` appends a ToolBlock keyed by call_id; `tool_result` updates it in place.
- `text_delta` appends to the trailing TextBlock, creating one if the tail isn't text.
- On `run_completed`, tool/thinking blocks collapse into a one-line summary
  ("Worked for 14s · 5 steps") that expands on click — Claude Code's exact pattern.
- Citation chips activate when `citation_map` arrives; clicking one drives the PDF
  visualizer (open doc → page → highlight bbox).
- A transient status line under the message mirrors the latest active step for glanceability.

What the user sees end-to-end:

> *Thinking…* → ✓ Read TOC of *Physics Module 2* → ✓ Searched "dimensional analysis" — 9
> passages → ✓ Searched question bank — 4 PYQs → answer streams in with [E1] [E2] chips →
> confidence chip → timeline collapses.
