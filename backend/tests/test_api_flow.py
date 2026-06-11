"""Gateway HTTP flow: signup → personal space → upload → ingest → structure.

Needs the compose stack (postgres + minio + redis). Ingestion runs inline by
monkeypatching the enqueue to call the AI pipeline directly with the parse cache
seeded (no Datalab key, no separate worker process).
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

os.environ.setdefault("EMBEDDINGS_FAKE", "1")
os.environ.setdefault("AUTH_MODE", "dev")

FIXTURE = Path(__file__).resolve().parents[2] / "ai" / "tests" / "fixtures" / "marker_sample.json"

pytestmark = pytest.mark.asyncio


async def _stack_up() -> bool:
    try:
        from relearn_db.engine import create_engine_and_sessionmaker

        engine, _ = create_engine_and_sessionmaker()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
async def client(monkeypatch):
    if not await _stack_up():
        pytest.skip("compose stack not running")

    # run ingestion inline instead of via the arq worker
    from relearn_ai import storage as ai_storage
    from relearn_ai.ingestion.pipeline import run_pipeline
    from relearn_backend import queue
    from relearn_backend.db import _sessionmaker

    async def fake_enqueue(job_id, *, checksum, doc_type, title):
        await ai_storage.put_json(ai_storage.parse_key(checksum), json.loads(FIXTURE.read_text()))
        async with _sessionmaker() as s:
            await run_pipeline(
                s, uuid.UUID(job_id), checksum=checksum, doc_type=doc_type, title=title
            )

    monkeypatch.setattr(queue, "enqueue_ingest", fake_enqueue)
    # resources_router imported the symbol directly — patch there too
    from relearn_backend.routers import resources_router

    monkeypatch.setattr(resources_router, "enqueue_ingest", fake_enqueue)

    from relearn_backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_full_flow(client):
    email = f"{uuid.uuid4().hex}@test.dev"
    r = await client.post("/auth/signup", json={"email": email, "password": "pw123456"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # personal space auto-created at signup
    r = await client.get("/spaces", headers=headers)
    assert r.status_code == 200
    spaces = r.json()
    assert len(spaces) == 1 and spaces[0]["role"] == "owner"
    space_id = spaces[0]["id"]

    # upload a PDF → inline ingest
    r = await client.post(
        f"/spaces/{space_id}/resources",
        headers=headers,
        files={"file": ("biology.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"doc_type": "textbook", "title": "Biology"},
    )
    assert r.status_code == 201, r.text
    resource_id = r.json()["id"]

    # status reflects ready (ingest ran inline during upload)
    r = await client.get(f"/spaces/{space_id}/resources/{resource_id}/status", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "ready", r.json()

    # resource now carries a document_id
    r = await client.get(f"/spaces/{space_id}/resources", headers=headers)
    document_id = r.json()[0]["document_id"]
    assert document_id

    # document meta has page dims + a presigned pdf url
    r = await client.get(f"/documents/{document_id}", headers=headers)
    assert r.status_code == 200
    meta = r.json()
    assert meta["page_dimensions"]["0"] == [612.0, 792.0]
    assert meta["pdf_url"].startswith("http")

    # structure tree browsable
    r = await client.get(f"/documents/{document_id}/structure", headers=headers)
    assert r.status_code == 200
    headings = {n["heading_text"] for n in r.json()}
    assert "Chapter 1 Cell Biology" in headings


async def test_scope_enforced(client):
    # two users; user B cannot see user A's space
    a = (await client.post("/auth/signup", json={"email": f"{uuid.uuid4().hex}@t.dev", "password": "pw123456"})).json()
    b = (await client.post("/auth/signup", json={"email": f"{uuid.uuid4().hex}@t.dev", "password": "pw123456"})).json()
    a_headers = {"Authorization": f"Bearer {a['access_token']}"}
    b_headers = {"Authorization": f"Bearer {b['access_token']}"}

    a_space = (await client.get("/spaces", headers=a_headers)).json()[0]["id"]
    r = await client.get(f"/spaces/{a_space}", headers=b_headers)
    assert r.status_code == 404  # not 403 — existence hidden


async def test_unauthenticated_rejected(client):
    # no bearer token → unauthenticated
    assert (await client.get("/spaces")).status_code in (401, 403)
