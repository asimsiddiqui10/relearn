# Backend gateway

The only public door (spec/01). Auth, spaces, resources, upload, document/visualizer
read paths. Holds zero AI logic — ingestion runs in the AI service worker; chat
(Phase 1) will be proxied as an SSE stream.

```
relearn_backend/
  config.py     settings (env)
  db.py         async session dependency (shared relearn_db schema)
  auth.py       JWT verify — dev (local HS256) | oidc (Cognito JWKS); one interface
  access.py     per-space membership check, enforced in SQL on every request
  storage.py    S3/MinIO upload + presigned GET for the visualizer
  queue.py      arq enqueue (worker lives in the AI service)
  schemas.py    request/response models
  routers/      auth, spaces, resources (upload+status), documents (structure+meta)
  main.py       app wiring + CORS
```

Run: `uv run uvicorn relearn_backend.main:app --port 8000 --reload`

## Auth modes
- `AUTH_MODE=dev` (Phase 0): backend issues + verifies HS256 tokens — no AWS.
- `AUTH_MODE=oidc`: verifies RS256 against the issuer JWKS (Cognito). Swapping
  issuers (Keycloak for institute SSO) is an env change, not a code change.

## Tests
`EMBEDDINGS_FAKE=1 uv run pytest tests` (needs the compose stack; ingestion runs
inline via the AI pipeline with the parse cache seeded).
