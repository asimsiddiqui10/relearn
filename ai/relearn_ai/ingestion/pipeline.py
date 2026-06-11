"""Ingestion pipeline (spec/05): dedup → parse(cache) → normalize → map → embed
→ gate → summarize → commit.

Rule-first; the LLM is a repair/assist layer only. The S3 parse cache
(parses/{sha256}.json) is global and written exactly once per unique file —
Datalab is never paid twice.
"""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import (
    Chunk,
    Document,
    Image,
    IngestJob,
    MarkerIngestRun,
    Resource,
    StructureNode,
)

from relearn_ai import storage
from relearn_ai.config import get_settings
from relearn_ai.ingestion import datalab
from relearn_ai.ingestion.gates import run_quality_gates
from relearn_ai.ingestion.marker_payload import (
    MARKER_INGEST_PARSER_VERSION,
    document_metadata_for_db,
    normalize_marker_payload,
)
from relearn_ai.ingestion.normalize_tree import normalize_marker_tree
from relearn_ai.ingestion.tree_mapper import (
    MappedDocument,
    map_marker_document_tree,
    strip_images_recursive,
)
from relearn_ai.llm import embed
from relearn_ai.observability import observe

logger = logging.getLogger(__name__)


class IngestFailure(RuntimeError):
    """Human-readable, terminal ingestion failure (no retry)."""


async def _set_stage(session: AsyncSession, job: IngestJob, stage: str) -> None:
    job.stage = stage
    job.status = "running"
    await session.commit()
    logger.info("ingest job %s → %s", job.id, stage)


@observe(name="run_pipeline")
async def run_pipeline(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    checksum: str,
    doc_type: str,
    title: str,
) -> None:
    """Full pipeline for one ingest job. Raises IngestFailure for terminal errors."""
    settings = get_settings()
    job = (
        await session.execute(select(IngestJob).where(IngestJob.id == job_id))
    ).scalar_one()
    resource = (
        await session.execute(select(Resource).where(Resource.id == job.resource_id))
    ).scalar_one()

    try:
        resource.status = "ingesting"
        await session.commit()

        # 0. DEDUP — re-upload within the space short-circuits
        existing = (
            await session.execute(
                select(Document).where(
                    Document.space_id == resource.space_id, Document.checksum == checksum
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status == "ready":
            resource.document_id = existing.id
            resource.status = "ready"
            job.status = "succeeded"
            job.stage = "dedup"
            await session.commit()
            logger.info("dedup hit: resource %s → existing document %s", resource.id, existing.id)
            return

        # 1. PARSE — cache first, Datalab once, cache forever
        await _set_stage(session, job, "parse")
        raw_payload = await storage.get_json(storage.parse_key(checksum))
        if raw_payload is None:
            pdf_bytes = await storage.get_bytes(storage.pdf_key(checksum))
            if pdf_bytes is None:
                raise IngestFailure(f"PDF missing from object storage: {storage.pdf_key(checksum)}")
            raw_payload = await datalab.parse_pdf(
                pdf_bytes, f"{title}.pdf", api_key=settings.datalab_api_key
            )
            await storage.put_json(storage.parse_key(checksum), raw_payload)
            logger.info("parse cached: %s", storage.parse_key(checksum))
        else:
            logger.info("parse cache hit: %s — Datalab skipped", storage.parse_key(checksum))

        # 2. NORMALIZE
        await _set_stage(session, job, "normalize")
        document_root, _envelope = normalize_marker_payload(raw_payload)
        normalize_marker_tree(document_root)

        # 3. MAP
        await _set_stage(session, job, "map")
        document = existing or Document(
            space_id=resource.space_id,
            file_path=storage.pdf_key(checksum),
            checksum=checksum,
            doc_type=doc_type,
            status="pending",
        )
        if existing is None:
            session.add(document)
            await session.flush()
        mapped = map_marker_document_tree(document_root, document.id, document_title=title)

        page_dimensions = _page_dimensions(document_root)
        metadata = document_metadata_for_db(document_root) or {}
        metadata["page_dimensions"] = page_dimensions
        document.metadata_json = metadata

        # 4. EMBED
        await _set_stage(session, job, "embed")
        vectors = await embed([c.content for c in mapped.chunks])

        # 5. GATE (repair pass arrives with the LLM layer in Phase 1 — for now a
        #    gate failure is terminal with a readable reason, never silent garbage)
        await _set_stage(session, job, "gate")
        gates = run_quality_gates(mapped, page_count=len(page_dimensions))
        if not gates.passed:
            raise IngestFailure("quality gates failed: " + "; ".join(gates.failures))

        # 6. extract + upload image bytes
        await _set_stage(session, job, "images")
        image_files = await _upload_images(document_root, mapped, checksum)

        # 7. SUMMARIZE — deferred to Phase 1 (needs the small-model role wired
        #    into prompts); structure browsing works without summaries.

        # 8. COMMIT — one transaction for the whole corpus
        await _set_stage(session, job, "commit")
        session.add(
            MarkerIngestRun(
                document_id=document.id,
                raw_payload=None,  # raw JSON lives in S3 (parses/{sha}); keep normalized tree
                normalized_tree=strip_images_recursive(document_root),
                marker_version=MARKER_INGEST_PARSER_VERSION,
            )
        )
        # Insert structure nodes tier-by-tier (shallow depth first) so every
        # parent_node_id target exists before its children — SQLAlchemy does not
        # order intra-table rows for a self-referential FK without a relationship.
        for depth in sorted({n.depth for n in mapped.structure_nodes}):
            for n in (n for n in mapped.structure_nodes if n.depth == depth):
                flags = dict(n.normalization_flags or {})
                if n.numbering_prefix:
                    flags["numbering_prefix"] = n.numbering_prefix
                session.add(
                    StructureNode(
                        id=n.id,
                        document_id=n.document_id,
                        parent_node_id=n.parent_node_id,
                        depth=n.depth,
                        heading_level=n.heading_level,
                        heading_text=n.heading_text,
                        node_type=n.node_type,
                        structure_path=n.structure_path,
                        heading_breadcrumb=n.heading_breadcrumb,
                        page_start=n.page_start,
                        page_end=n.page_end,
                        subtree_chunk_count=n.subtree_chunk_count,
                        subtree_token_count=n.subtree_token_count,
                        normalization_flags=flags or None,
                        marker_block_id=n.marker_block_id or None,
                    )
                )
            await session.flush()
        for img in mapped.images:
            session.add(
                Image(
                    id=img.id,
                    document_id=img.document_id,
                    structure_node_id=img.structure_node_id,
                    page_number=img.page_number,
                    bbox=img.bbox,
                    file_path=image_files.get(img.marker_block_id),
                    caption=img.caption,
                    figure_ref_norm=img.figure_ref_norm,
                )
            )
        await session.flush()  # images before chunks (attached_image_id FK)
        for chunk, vector in zip(mapped.chunks, vectors, strict=True):
            session.add(
                Chunk(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    structure_node_id=chunk.structure_node_id,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    content_html=chunk.content_html,
                    page_number=chunk.page_number,
                    bbox=chunk.bbox,
                    polygon=chunk.polygon,
                    token_count=chunk.token_count,
                    structure_path=chunk.structure_path,
                    heading_breadcrumb=chunk.heading_breadcrumb,
                    attached_image_id=chunk.attached_image_id,
                    marker_block_id=chunk.marker_block_id or None,
                    embedding=vector,
                )
            )

        document.status = "ready"
        resource.document_id = document.id
        resource.status = "ready"
        job.status = "succeeded"
        job.stage = "done"
        await session.commit()
        logger.info(
            "ingested document %s: %d nodes, %d chunks, %d images",
            document.id, len(mapped.structure_nodes), len(mapped.chunks), len(mapped.images),
        )

    except IngestFailure as exc:
        await session.rollback()
        job.status = "failed"
        job.error = str(exc)
        job.stage = job.stage or "unknown"
        resource.status = "failed"
        await session.commit()
        logger.error("ingest job %s failed (terminal): %s", job.id, exc)
    except Exception as exc:
        await session.rollback()
        job.attempts += 1
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        resource.status = "failed"
        await session.commit()
        raise  # transient — arq retries


def _page_dimensions(document_root: dict[str, Any]) -> dict[str, list[float]]:
    """{page_number: [width, height]} in Marker coordinates — the visualizer's
    one coordinate space (spec/11)."""
    dims: dict[str, list[float]] = {}
    for page in document_root.get("children") or []:
        if not isinstance(page, dict) or page.get("block_type") != "Page":
            continue
        from relearn_ai.ingestion.tree_mapper import parse_page_number

        pnum = parse_page_number(page.get("id"))
        bbox = page.get("bbox")
        if pnum is not None and isinstance(bbox, list) and len(bbox) >= 4:
            dims[str(pnum)] = [float(bbox[2]), float(bbox[3])]
    return dims


async def _upload_images(
    document_root: dict[str, Any], mapped: MappedDocument, checksum: str
) -> dict[str, str]:
    """Decode base64 images from Marker blocks, upload to S3, return
    {marker_block_id: s3_key}."""
    b64_by_block: dict[str, str] = {}

    def walk(node: dict[str, Any]) -> None:
        imgs = node.get("images")
        if isinstance(imgs, dict):
            for key, val in imgs.items():
                if isinstance(val, str) and len(val) > 200:
                    b64_by_block[str(key)] = val
        for c in node.get("children") or []:
            if isinstance(c, dict):
                walk(c)

    walk(document_root)

    out: dict[str, str] = {}
    counter = 0
    for img in mapped.images:
        b64 = b64_by_block.get(img.marker_block_id)
        if not b64:
            continue
        try:
            data = base64.b64decode(b64)
        except Exception:
            logger.warning("undecodable image for block %s", img.marker_block_id)
            continue
        key = storage.image_key(checksum, counter)
        await storage.put_bytes(key, data, content_type="image/png")
        out[img.marker_block_id] = key
        counter += 1
    return out
