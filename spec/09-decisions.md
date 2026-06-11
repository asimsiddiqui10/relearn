# Decision Record (final)

Every architectural decision, settled. If a future change contradicts one of these,
update this file with the reason.

| # | Decision | Resolution | Why |
|---|---|---|---|
| 1 | Backend language | **FastAPI (Python)** — one language across backend + AI service | Solo dev, one toolchain; Mike's TS patterns are distilled into the spec, not needed as living reference |
| 2 | Orchestration framework | **None** — no LangChain/LangGraph/LlamaIndex/MLflow | Agent loop is ~200 lines we control; evidence/citation contract must stay ours; durability = arq + checkpoints, not a framework |
| 3 | Auth | **AWS Cognito** (Lite tier, 10k MAU free) | Pay-only-AWS constraint; Supabase free tier pauses; Clerk per-MAU pricing punishes B2B scale. Custom login UI; `react-oidc-context` frontend; local JWKS verification in FastAPI middleware. Keycloak reconsidered at white-label stage |
| 4 | Model access | **OpenRouter for dev/benching; direct providers (Together/Fireworks) per bench winner; Bedrock only as optional Claude consolidation** | One OpenAI-compatible endpoint covers Gemma/Kimi/Qwen/GLM/Claude/OpenAI/Gemini; Bedrock can't cover the bench list |
| 5 | Dev-default model | **Gemini 2.5 Flash** via Google's OpenAI-compatible endpoint (existing free key) | Build loop/tools/streaming at zero cost; bench Kimi K2 / Qwen3-235B / GLM-4.6 in Phase 1; Claude Sonnet as removable debug baseline |
| 6 | Embeddings | **BGE-M3, local** | Free re-embeds, multilingual for Hindi later |
| 7 | Parsing | **Marker via Datalab API**; self-host marker-pdf only when volume justifies | Bboxes + structure are the citation moat |
| 8 | Parse persistence | **User-provided S3 bucket**: `pdfs/{sha256}.pdf` + `parses/{sha256}.json`, global cache, written once, never deleted | DB/Docker are disposable; Datalab never paid twice |
| 9 | Document dedup scope | **Within a space**: UNIQUE (space_id, checksum); no cross-space sharing yet | Simplicity now; global parse cache makes future migration free |
| 10 | Data migration from v1 | **None** — fresh ingestion; code-level salvage only (see `reference/v1/`) | v1 data was dev data |
| 11 | Services | **3**: Next.js frontend / FastAPI gateway / Python AI service (agent runtime + arq ingestion worker) — one Postgres schema, hard FKs, backend is the only public door | v1's sin was soft FKs + cross-service sync, not service count |
| 12 | Job queue | **arq on Redis** | Redis alone is just a broker; arq supplies workers/retries/timeouts as a pip package |
| 13 | First demo vertical | **NEET** | Two-column paper format already analyzed against Marker output |
| 14 | LLM observability | **Langfuse, self-hosted, day one**, instrumented in `llm.py` | User-proven (v1 `tracing.py` pattern); provider comparisons in dashboards |
| 15 | Error tracking | **GlitchTip** (Sentry-SDK-compatible, self-hosted) | No extra SaaS bill; swap to hosted Sentry = one DSN |
| 16 | Frontend reference | **MikeOSS patterns + same libraries, zero copied code** (AGPL-3.0) | Same deps are safe (MIT); source is not. Fonts: Inter + EB Garamond |
| 17 | Visualizer | **Clean-room rebuild** — only two v1 ideas survive (raw Marker coords; stretch-fit SVG overlay) | v1 component was buggy; bug classes are now explicit requirements in spec 11 |
| 18 | Deployment | **All-AWS**: dev = local Docker; prod v1 = one EC2 + S3 + CloudFront; managed services (RDS/ECS) on signal, not ambition; Activate credits first | Single bill, simple ops |
| 19 | Dev environment | **Dev container, editor-agnostic**: host installs only Docker Desktop + git; `docker compose exec dev zsh` → `claude` inside; agents/commands always in-container, humans may edit from host (Cursor on the bind mount) | Zero host dependencies; safe allow-all Claude Code (bounded blast radius, scoped IAM, capped API keys) |
| 20 | Old repos | **Deletable** — MikeOSS immediately (everything learned is in this spec; AGPL forbids copying anyway); mvp/v1 after `reference/v1/` salvage (done) | Prevents accidental complexity-copying; spec + salvage folder are the only inputs to the new build |
