from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import Document, IngestJob, Resource

from relearn_backend import storage
from relearn_backend.access import require_member
from relearn_backend.auth import Principal, current_principal
from relearn_backend.db import get_session
from relearn_backend.queue import enqueue_ingest
from relearn_backend.schemas import IngestStatus, ResourceOut

router = APIRouter(prefix="/spaces/{space_id}/resources", tags=["resources"])

_DOC_TYPES = {"textbook", "notes", "question_paper", "slides"}


@router.get("", response_model=list[ResourceOut])
async def list_resources(
    space_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_member(session, space_id, principal.user_id)
    rows = (
        await session.execute(
            select(Resource).where(Resource.space_id == space_id).order_by(Resource.created_at)
        )
    ).scalars().all()
    return rows


@router.post("", response_model=ResourceOut, status_code=201)
async def upload_resource(
    space_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: str = Form("textbook"),
    title: str | None = Form(None),
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_member(session, space_id, principal.user_id)
    if doc_type not in _DOC_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"bad doc_type {doc_type!r}")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty file")
    checksum = hashlib.sha256(data).hexdigest()
    resolved_title = title or (file.filename or "Untitled").rsplit(".", 1)[0]

    # upload bytes once (idempotent — key is content-addressed)
    await storage.put_pdf(checksum, data)

    resource = Resource(
        space_id=space_id,
        type="document",
        title=resolved_title,
        uploaded_by=principal.user_id,
        status="pending",
    )
    session.add(resource)
    await session.flush()

    # dedup hint: if a ready document already exists in this space, link immediately
    existing = (
        await session.execute(
            select(Document).where(
                Document.space_id == space_id,
                Document.checksum == checksum,
                Document.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        resource.document_id = existing.id
        resource.status = "ready"
        await session.commit()
        return resource

    job = IngestJob(resource_id=resource.id, status="queued")
    session.add(job)
    await session.commit()

    await enqueue_ingest(
        str(job.id), checksum=checksum, doc_type=doc_type, title=resolved_title
    )
    return resource


@router.get("/{resource_id}/status", response_model=IngestStatus)
async def ingest_status(
    space_id: uuid.UUID,
    resource_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await require_member(session, space_id, principal.user_id)
    resource = (
        await session.execute(
            select(Resource).where(Resource.id == resource_id, Resource.space_id == space_id)
        )
    ).scalar_one_or_none()
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    job = (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.resource_id == resource_id)
            .order_by(IngestJob.created_at.desc())
        )
    ).scalars().first()
    return IngestStatus(
        resource_id=resource.id,
        status=resource.status,
        stage=job.stage if job else None,
        error=job.error if job else None,
    )
