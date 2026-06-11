"""Retrieval tools (spec/03): search_chunks, get_toc, read_section, expand_chunk,
get_images. Every corpus-touching tool registers evidence and is scoped in SQL.

Documents are addressed by stable per-run slugs (doc-0, doc-1 …) in model
context — the model never sees raw UUIDs (Mike's pattern). The slug map is built
from the run's allowed documents.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import Chunk, Image, StructureNode

from relearn_ai.agent.evidence import RunContext
from relearn_ai.agent.retrieval import hybrid_search
from relearn_ai.agent.tools.base import Tool, ToolResult

_READ_SECTION_TOKEN_CAP = 4000


def doc_slugs(document_ids: list[uuid.UUID]) -> dict[str, uuid.UUID]:
    return {f"doc-{i}": did for i, did in enumerate(document_ids)}


def _slug_for(ctx: RunContext, document_id: uuid.UUID) -> str:
    for slug, did in doc_slugs(ctx.document_ids).items():
        if did == document_id:
            return slug
    return "doc-?"


def _resolve_slug(ctx: RunContext, slug: str) -> uuid.UUID | None:
    return doc_slugs(ctx.document_ids).get(slug)


# ---------------------------------------------------------------------------
# search_chunks
# ---------------------------------------------------------------------------


class SearchChunksArgs(BaseModel):
    query: str = Field(description="What to search for, in natural language.")
    doc_slugs: list[str] | None = Field(
        default=None, description="Restrict to these document slugs (e.g. ['doc-0']). Omit for all."
    )
    top_k: int = Field(default=12, ge=1, le=30)


class SearchChunks(Tool):
    name = "search_chunks"
    description = (
        "Hybrid semantic + lexical search over the space's documents. Returns "
        "passages with evidence ids ([E#]) you must cite. Search before answering."
    )
    Args = SearchChunksArgs

    def label(self, args: SearchChunksArgs) -> str:
        scope = ", ".join(args.doc_slugs) if args.doc_slugs else "all resources"
        return f'Searching "{args.query}" in {scope}…'

    async def run(self, args: SearchChunksArgs, ctx: RunContext, db: AsyncSession) -> ToolResult:
        scope_ids = ctx.document_ids
        if args.doc_slugs:
            scope_ids = [d for s in args.doc_slugs if (d := _resolve_slug(ctx, s))]
        hits = await hybrid_search(args.query, db, scope_ids, top_k=args.top_k)

        if not hits:
            return ToolResult({"results": []}, "No passages found")

        chunk_ids = [h.chunk_id for h in hits]
        chunks = {
            c.id: c
            for c in (
                await db.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
            ).scalars()
        }
        results, new_eids = [], []
        sections: set[uuid.UUID] = set()
        for h in hits:
            chunk = chunks.get(h.chunk_id)
            if chunk is None:
                continue
            item = ctx.registry.register(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                page=chunk.page_number,
                bbox=chunk.bbox,
                polygon=chunk.polygon,
                heading_breadcrumb=chunk.heading_breadcrumb,
                text=chunk.content,
            )
            new_eids.append(item.eid)
            if chunk.structure_node_id:
                sections.add(chunk.structure_node_id)
            results.append(
                {
                    "eid": item.eid,
                    "doc": _slug_for(ctx, chunk.document_id),
                    "page": chunk.page_number,
                    "section": chunk.heading_breadcrumb,
                    "text": chunk.content,
                }
            )
        summary = f"Found {len(results)} passages across {len(sections)} sections"
        return ToolResult({"results": results}, summary, new_eids)


# ---------------------------------------------------------------------------
# get_toc
# ---------------------------------------------------------------------------


class GetTocArgs(BaseModel):
    doc_slug: str = Field(description="Document slug, e.g. 'doc-0'.")


class GetToc(Tool):
    name = "get_toc"
    description = (
        "Table of contents (heading tree) of a document with per-section chunk "
        "and token counts — use it to judge scope and check coverage."
    )
    Args = GetTocArgs

    def label(self, args: GetTocArgs) -> str:
        return f"Reading the table of contents of {args.doc_slug}…"

    async def run(self, args: GetTocArgs, ctx: RunContext, db: AsyncSession) -> ToolResult:
        doc_id = _resolve_slug(ctx, args.doc_slug)
        if doc_id is None:
            return ToolResult({"error": f"unknown document {args.doc_slug}"}, "Unknown document")
        nodes = (
            await db.execute(
                select(StructureNode)
                .where(StructureNode.document_id == doc_id)
                .order_by(StructureNode.page_start, StructureNode.depth)
            )
        ).scalars().all()
        toc = [
            {
                "node_id": str(n.id),
                "depth": n.depth,
                "heading": n.heading_text,
                "pages": [n.page_start, n.page_end],
                "chunks": n.subtree_chunk_count,
                "tokens": n.subtree_token_count,
            }
            for n in nodes
        ]
        return ToolResult({"toc": toc}, f"{len(toc)} sections")


# ---------------------------------------------------------------------------
# read_section
# ---------------------------------------------------------------------------


class ReadSectionArgs(BaseModel):
    node_id: str = Field(description="A structure node id from get_toc.")


class ReadSection(Tool):
    name = "read_section"
    description = (
        "All chunks under a section (capped ~4k tokens; falls back to the section "
        "summary + child list when oversized). Registers each chunk as evidence."
    )
    Args = ReadSectionArgs

    def label(self, args: ReadSectionArgs) -> str:  # noqa: ARG002
        return "Reading a section…"

    async def run(self, args: ReadSectionArgs, ctx: RunContext, db: AsyncSession) -> ToolResult:
        try:
            node_id = uuid.UUID(args.node_id)
        except ValueError:
            return ToolResult({"error": "bad node_id"}, "Bad node id")
        node = (
            await db.execute(select(StructureNode).where(StructureNode.id == node_id))
        ).scalar_one_or_none()
        if node is None or node.document_id not in ctx.document_ids:
            return ToolResult({"error": "section not in scope"}, "Section out of scope")

        chunks = (
            await db.execute(
                select(Chunk)
                .where(Chunk.structure_node_id == node_id)
                .order_by(Chunk.page_number)
            )
        ).scalars().all()

        total = sum(c.token_count or 0 for c in chunks)
        if total > _READ_SECTION_TOKEN_CAP:
            children = (
                await db.execute(
                    select(StructureNode.id, StructureNode.heading_text).where(
                        StructureNode.parent_node_id == node_id
                    )
                )
            ).all()
            return ToolResult(
                {
                    "oversized": True,
                    "summary": node.summary,
                    "children": [{"node_id": str(c[0]), "heading": c[1]} for c in children],
                },
                f"Section too large ({total} tokens) — returned summary + {len(children)} children",
            )

        passages, new_eids = [], []
        for chunk in chunks:
            item = ctx.registry.register(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                page=chunk.page_number,
                bbox=chunk.bbox,
                polygon=chunk.polygon,
                heading_breadcrumb=chunk.heading_breadcrumb,
                text=chunk.content,
            )
            new_eids.append(item.eid)
            passages.append({"eid": item.eid, "page": chunk.page_number, "text": chunk.content})
        return ToolResult(
            {"heading": node.heading_text, "passages": passages},
            f"Read {len(passages)} passages from “{node.heading_text}”",
            new_eids,
        )


# ---------------------------------------------------------------------------
# expand_chunk
# ---------------------------------------------------------------------------


class ExpandChunkArgs(BaseModel):
    eid: str = Field(description="An evidence id (e.g. 'E3') to expand with neighbors.")


class ExpandChunk(Tool):
    name = "expand_chunk"
    description = (
        "Prev/next neighboring chunks + the parent heading for an evidence item — "
        "late expansion to get surrounding context."
    )
    Args = ExpandChunkArgs

    def label(self, args: ExpandChunkArgs) -> str:
        return f"Expanding {args.eid} with surrounding context…"

    async def run(self, args: ExpandChunkArgs, ctx: RunContext, db: AsyncSession) -> ToolResult:
        item = ctx.registry.get(args.eid)
        if item is None:
            return ToolResult({"error": f"unknown evidence {args.eid}"}, "Unknown evidence id")
        anchor = (
            await db.execute(select(Chunk).where(Chunk.id == item.chunk_id))
        ).scalar_one_or_none()
        if anchor is None:
            return ToolResult({"error": "chunk gone"}, "Chunk unavailable")

        # neighbors by structure node + page order
        neighbors = (
            await db.execute(
                select(Chunk)
                .where(Chunk.structure_node_id == anchor.structure_node_id)
                .order_by(Chunk.page_number, Chunk.id)
            )
        ).scalars().all()
        ids = [c.id for c in neighbors]
        idx = ids.index(anchor.id) if anchor.id in ids else -1
        window = neighbors[max(0, idx - 1) : idx + 2] if idx >= 0 else [anchor]

        new_eids = []
        passages = []
        for chunk in window:
            ev = ctx.registry.register(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                page=chunk.page_number,
                bbox=chunk.bbox,
                polygon=chunk.polygon,
                heading_breadcrumb=chunk.heading_breadcrumb,
                text=chunk.content,
            )
            new_eids.append(ev.eid)
            passages.append({"eid": ev.eid, "page": chunk.page_number, "text": chunk.content})
        return ToolResult(
            {"heading": anchor.heading_breadcrumb, "passages": passages},
            f"Expanded to {len(passages)} neighboring passages",
            new_eids,
        )


# ---------------------------------------------------------------------------
# get_images
# ---------------------------------------------------------------------------


class GetImagesArgs(BaseModel):
    doc_slug: str = Field(description="Document slug, e.g. 'doc-0'.")
    figure_ref: str | None = Field(
        default=None, description="Exact figure ref like 'figure_2_1' for a direct lookup."
    )
    query: str | None = Field(default=None, description="Semantic caption search instead.")


class GetImages(Tool):
    name = "get_images"
    description = (
        "Find figures/tables: by exact figure_ref (instant indexed lookup) or by "
        "a caption query. Returns image evidence with page and bbox."
    )
    Args = GetImagesArgs

    def label(self, args: GetImagesArgs) -> str:
        what = args.figure_ref or args.query or "figures"
        return f"Looking up {what} in {args.doc_slug}…"

    async def run(self, args: GetImagesArgs, ctx: RunContext, db: AsyncSession) -> ToolResult:
        doc_id = _resolve_slug(ctx, args.doc_slug)
        if doc_id is None:
            return ToolResult({"error": "unknown document"}, "Unknown document")
        stmt = select(Image).where(Image.document_id == doc_id)
        if args.figure_ref:
            stmt = stmt.where(Image.figure_ref_norm == args.figure_ref)
        images = (await db.execute(stmt.limit(10))).scalars().all()
        results = [
            {
                "image_id": str(im.id),
                "page": im.page_number,
                "caption": im.caption,
                "figure_ref": im.figure_ref_norm,
                "bbox": im.bbox,
            }
            for im in images
        ]
        return ToolResult({"images": results}, f"Found {len(results)} figures")
