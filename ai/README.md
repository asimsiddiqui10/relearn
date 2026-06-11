# AI service

Agent runtime (Phase 1) + arq ingestion worker. One package, two processes.

```
app/
  config.py          settings (env)
  storage.py         S3/MinIO: pdfs/, parses/ (global cache), images/
  observability.py   Langfuse @observe — no-op without keys
  llm/               role-based LLM access + models.yaml registry
  ingestion/         datalab client, normalize_tree, tree_mapper, gates, pipeline
  worker.py          arq WorkerSettings (ingest task)
  main.py            FastAPI health (agent runtime lands in Phase 1)
```

## Ingestion pipeline (spec/05)

`dedup → parse(S3 cache, else Datalab) → normalize → map → embed → gate → images → commit`

Rule-first; LLM is repair/assist only. The S3 parse cache (`parses/{sha256}.json`)
is written once per unique file — Datalab is never paid twice. `docker compose
down -v` then re-ingest replays from cache for free.

## Tests

```bash
# mapping heuristics — no infra
uv run pytest tests/test_tree_mapper.py

# end-to-end via parse-cache replay (needs compose stack up + schema migrated;
# EMBEDDINGS_FAKE=1 skips the BGE-M3 download with deterministic vectors)
EMBEDDINGS_FAKE=1 uv run pytest tests/
```
