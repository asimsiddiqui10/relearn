# Models

All open-source in production, all behind one abstraction layer so providers and models
swap by config — during testing we will freely mix Claude, Fireworks, OpenRouter,
Together, and self-hosted vLLM without touching application code.

## Provider abstraction layer (`llm.py`) — a hard requirement

**Application code never names a model or provider. It asks for a role.**

```python
await llm.complete(role="agent", messages=..., tools=...)   # roles: agent | small | vision
await llm.embed(texts)                                       # role: embeddings
# per-run override for benching/evals:
await llm.complete(role="agent", model_alias="claude-sonnet", ...)
```

Concrete models live in `models.yaml` — the registry:

```yaml
roles:                                  # dev bootstrap shown; production after Phase-1 bench
  agent:      {primary: gemini-flash}   # → bench winner, e.g. {primary: kimi-k2-openrouter, fallback: qwen3-235b}
  small:      {primary: gemini-flash}   # → e.g. qwen3-8b
  embeddings: {primary: bge-m3-local}

models:
  kimi-k2-openrouter:
    provider: openai_compat          # adapter to use
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    model_id: moonshotai/kimi-k2
    capabilities: {tool_calling: true, structured_output: true,
                   reasoning_content: true, parallel_tools: true}
    context_window: 128000
    cost_per_mtok: {input: 0.6, output: 2.5}
  gemini-flash:                      # dev default — free tier, OpenAI-compatible endpoint
    provider: openai_compat
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api_key_env: GEMINI_API_KEY
    model_id: gemini-2.5-flash
    capabilities: {tool_calling: true, structured_output: true,
                   reasoning_content: false, parallel_tools: true}
  claude-sonnet:
    provider: anthropic              # native adapter, dev baseline
    ...
```

**Dev bootstrap**: start with `agent`/`small` both pointed at `gemini-flash` (free tier) —
build the loop, tools, and streaming at zero cost; add OpenRouter when serious benching
begins. Gemini's OpenAI-compat shim doesn't expose reasoning tokens → no thinking blocks
in the UI until a model with `reasoning_content: true` is configured (graceful, by design).

Design rules:

1. **One internal format** for messages, tool calls, and stream deltas — ours, not any
   provider's. Adapters translate at the boundary; provider quirks (where reasoning
   tokens live, tool-call streaming shapes, response_format dialects) die inside the
   adapter. The agent loop never sees them.
2. **Two adapters cover everything**: `openai_compat` (vLLM, OpenRouter, Together,
   Fireworks, Groq — ~90% of cases) and `anthropic` (native, for Claude testing/baseline).
   Adding a provider = one adapter file max, usually just a yaml entry.
3. **Capability flags, not provider names, gate code paths**: no `structured_output` →
   Instructor retry path engages automatically; no `reasoning_content` → no thinking
   events, UI unaffected; no `parallel_tools` → loop serializes calls. Nothing breaks on
   switch — behavior degrades by declared capability.
4. **Per-run override** (`model_alias`) so the eval harness benches N models over the
   same question set with zero config edits.
5. **Langfuse instrumented here** — this layer is the single choke point: every call
   traced with role, alias, provider, latency, tokens, cost. Provider/model comparisons
   happen in Langfuse dashboards, not in guesswork.
6. **Startup validation**: on boot, each configured model gets a cheap probe; declared
   capabilities that fail (e.g. provider silently ignoring `response_format`) fail loudly
   at startup, not mid-run.

## Roster

| Role | Primary pick | Alternates | Notes |
|---|---|---|---|
| **Agent model** (the loop) | **Kimi K2** or **Qwen3-235B-A22B** (hosted: OpenRouter / Together / Fireworks) | GLM-4.6, DeepSeek V3.2 | Tool-calling quality is the single biggest risk in the architecture. Choice is empirical — benched on our eval set in Phase 1. |
| **Small model** (ingest summaries, classification, repair, labels that ever need language) | Qwen3-8B (hosted; self-host later) | Llama-3.1-8B, Qwen3-4B | Cheap jobs only. |
| **Embeddings** | **BGE-M3** (1024-d) | Qwen3-Embedding-0.6B | Multilingual (Hindi/Hinglish later). Self-hostable on CPU/small GPU. Replaces v1's Gemini embeddings → re-embed during port. |
| **Reranker** (post-MVP, only if evals demand) | BGE-reranker-v2-m3 | Qwen3-Reranker | RRF fusion + heading boost may be enough; measure first. |
| **Vision** (question-paper diagrams, handwritten — later) | Qwen2.5-VL-72B (hosted) | Qwen2.5-VL-7B self-hosted | Post-MVP. |
| **Parsing** | Marker via Datalab API | Self-hosted `marker-pdf` (GPU) | Self-host when volume justifies ops. |

## Dev baseline rule

During Phases 0–1, keep a strong closed model (Claude Sonnet, via the same
OpenAI-compatible wrapper) configured as a **debug baseline**. When the agent misbehaves,
run the same query against the baseline: if it also fails → our loop/tools/prompts are
broken; if it succeeds → the OSS model is the weakness. Without this you debug model
weakness as if it were your bug and lose weeks. Lock in the OSS model once the harness is
proven; the baseline is removable by config.

## Model benching (Phase 1, week ~3)

Bench Kimi K2 vs Qwen3-235B vs GLM-4.6 on the eval set (see 07): tool-call validity rate,
coverage of expected evidence, citation precision, unsupported-claim rate, latency, cost
per answer. Pick one primary + one fallback.

## Structured outputs

vLLM (and most hosted OSS providers) support JSON-schema-guided decoding — used for
question extraction, classification, and any structured pipeline outputs. Pydantic models
are the single source of schema truth (tools and structured outputs alike).

## Hosting strategy

Note on AWS Bedrock: unlike auth, model APIs are pure pay-per-token (no subscription,
nothing pauses), so the "AWS-only billing" constraint is relaxed here. Bedrock cannot
cover our benching list (no Gemma/Gemini, no OpenAI proprietary; OSS catalog lags; best
models often us-east-1 only; non-OpenAI-compatible Converse API needs its own adapter).
Its role: **optional production consolidation** — if the bench winner is Claude, a
`bedrock` adapter puts inference on the AWS bill and burns Activate credits. Never the
exploration tool.

1. **Now (MVP/benching)**: **OpenRouter only** — one key, one OpenAI-compatible endpoint,
   every candidate model (Gemma, Kimi, Qwen, GLM, Claude, OpenAI, Gemini); model swap =
   one string in models.yaml. Direct providers (Together/Fireworks) adopted per-model
   after the bench picks winners, when their pricing/latency beats the routed path.
2. **First institute**: one GPU box (RTX 4090 / A10) running vLLM for small model +
   embeddings + Marker. Agent model stays API.
3. **Scale**: move the agent model to self-hosted vLLM when per-student economics flip
   the math. Never buy GPUs before product-market fit.

## Cost note

Agentic answers cost 3–5× a one-shot RAG answer (multiple model calls per query). Planned
mitigation (post-MVP, once real traffic shows the distribution): a **fast path** — simple
factual queries get single-search + one-shot cited answer with no loop; the agent path is
reserved for broad/multi-doc/ambiguous queries. Build the agent path first; add the cheap
path from data, not guesses.
