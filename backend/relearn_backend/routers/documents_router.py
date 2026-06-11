"""Document structure + visualizer geometry (read paths for the frontend)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import Document, StructureNode

from relearn_backend import storage
from relearn_backend.access import require_member
from relearn_backend.auth import Principal, current_principal
from relearn_backend.db import get_session
from relearn_backend.schemas import DocumentMeta, StructureNodeOut

router = APIRouter(prefix="/documents", tags=["documents"])


async def _load_document(session: AsyncSession, document_id: uuid.UUID, user_id: str) -> Document:
    document = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    await require_member(session, document.space_id, user_id)  # scope check
    return document


@router.get("/{document_id}", response_model=DocumentMeta)
async def get_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    document = await _load_document(session, document_id, principal.user_id)
    meta = document.metadata_json or {}
    return DocumentMeta(
        id=document.id,
        doc_type=document.doc_type,
        status=document.status,
        page_dimensions=meta.get("page_dimensions", {}),
        pdf_url=await storage.presign_get(document.file_path),
    )


@router.get("/{document_id}/structure", response_model=list[StructureNodeOut])
async def get_structure(
    document_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await _load_document(session, document_id, principal.user_id)
    nodes = (
        await session.execute(
            select(StructureNode)
            .where(StructureNode.document_id == document_id)
            .order_by(StructureNode.page_start, StructureNode.depth)
        )
    ).scalars().all()
    return nodes
