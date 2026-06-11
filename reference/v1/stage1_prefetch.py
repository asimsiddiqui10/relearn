"""Stage 1 — Hybrid prefetch.

Semantic + lexical retrieval, fused with RRF, and aggregated into chunk-level
and node-level candidates with global and candidate-level stats. No section
expansion or heavy reranking happens here — Stage 2 picks ids, Stage 3
deterministically resolves them.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.ingestion.embedder import embed_texts
from app.rag.models import (
    ChunkCandidate,
    NodeCandidate,
    PrefetchResult,
    PrefetchStats,
    ScopedContext,
    SpaceContext,
)
from app.rag.tracing import observe, update_current_observation

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 20
_RRF_K = 60.0
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
# Additive boost for chunks whose node heading matches a query term. Calibrated
# so a single-source heading-match hit (1/61 ≈ 0.0164) outranks a dual-source
# non-heading hit at mid-ranks (e.g. sem_rk=9 + lex_rk=3 ≈ 0.0304). Without it
# short queries like "P/O ratio?" lose their correct section to body-text
# chunks in adjacent sections that happen to contain the common tokens.
_HEADING_MATCH_BOOST = 0.02


def _build_or_tsquery(query: str) -> str:
    """Turn free-text into an OR-joined to_tsquery input.

    Why: websearch_to_tsquery uses AND — it silently returns zero hits when
    a single chunk doesn't contain every query term, which is the common case
    for RAG. OR keeps any-term-overlap as signal and lets RRF fuse it.
    """

    tokens = _TOKEN_RE.findall(query)
    return " | ".join(tokens)


@dataclass
class _SearchHit:
    """Raw per-source hit before RRF fusion."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    page_number: int | None
    heading_text: str | None
    score: float
    heading_match: bool = False


# ---------------------------------------------------------------------------
# Stage 1 entry point
# ---------------------------------------------------------------------------


@observe(name="stage1_prefetch")
async def stage1_prefetch(
    query: str,
    context: ScopedContext,
    db: AsyncSession,
    *,
    top_k: int = _DEFAULT_TOP_K,
) -> PrefetchResult:
    """Run hybrid retrieval and build planner-facing candidates + stats."""

    sem_hits = await _vector_search(
        query,
        db,
        document_id=context.document_id,
        document_ids=context.document_ids,
        space_id=context.space_id,
        top_k=top_k,
    )
    lex_hits = await _fulltext_search(
        query,
        db,
        document_id=context.document_id,
        document_ids=context.document_ids,
        space_id=context.space_id,
        top_k=top_k,
    )

    chunk_candidates, node_candidates, stats = await _build_candidates(
        sem_hits, lex_hits, context, db, top_k=top_k
    )

    space_context = await _fetch_space_context(context, db)
    last_turn = await _fetch_last_turn(context)

    result = PrefetchResult(
        chunk_candidates=chunk_candidates,
        node_candidates=node_candidates,
        stats=stats,
        space_context=space_context,
        last_turn=last_turn,
    )

    update_current_observation(
        input={"query": query, "top_k": top_k},
        output={
            "chunk_candidates": len(chunk_candidates),
            "node_candidates": len(node_candidates),
            "stats": stats.__dict__,
            "top_chunks": [
                {
                    "chunk_id": c.chunk_id[:8],
                    "doc_id": c.document_id[:8],
                    "node_id": c.structure_node_id[:8] if c.structure_node_id else None,
                    "sem_rank": c.sem_rank,
                    "lex_rank": c.lex_rank,
                    "fused_score": round(c.fused_score, 4),
                }
                for c in chunk_candidates[:5]
            ],
        },
    )
    return result


# ---------------------------------------------------------------------------
# Retrieval primitives
# ---------------------------------------------------------------------------


def _build_scope(
    params: dict,
    document_id: uuid.UUID | None,
    document_ids: list[uuid.UUID] | None,
    space_id: uuid.UUID | None,
) -> str:
    if document_id:
        params["doc_id"] = str(document_id)
        return "AND c.document_id = :doc_id"
    if document_ids:
        params["doc_ids"] = [str(d) for d in document_ids]
        return "AND c.document_id = ANY(:doc_ids)"
    if space_id:
        params["space_id"] = str(space_id)
        return """
            AND EXISTS (
                SELECT 1
                FROM documents d
                WHERE d.id = c.document_id
                  AND d.space_id = :space_id
            )
        """
    return ""


@observe(name="stage1_vector_search")
async def _vector_search(
    query: str,
    db: AsyncSession,
    *,
    document_id: uuid.UUID | None,
    document_ids: list[uuid.UUID] | None,
    space_id: uuid.UUID | None,
    top_k: int,
) -> list[_SearchHit]:
    """Semantic retrieval over chunk embeddings."""

    try:
        vectors = await embed_texts([query])
    except Exception as exc:
        logger.warning("Embedding API error (%s) — skipping semantic search", exc)
        return []

    if not vectors:
        logger.warning("Empty embedding response — skipping semantic search")
        return []

    query_vec = vectors[0]
    if not query_vec or any(not math.isfinite(v) for v in query_vec):
        logger.warning(
            "Query embedding is empty or contains NaN/Inf — skipping semantic search"
        )
        return []
    if all(v == 0.0 for v in query_vec):
        logger.warning("Query embedding is all zeros — skipping semantic search")
        return []

    vec_literal = "'[" + ",".join(str(v) for v in query_vec) + "]'::vector"

    params: dict = {"limit": top_k}
    scope = _build_scope(params, document_id, document_ids, space_id)

    sql = f"""
        SELECT c.id, c.document_id, c.structure_node_id, c.page_number,
               sn.heading_text,
               1 - (c.embedding <=> {vec_literal}) AS similarity
        FROM chunks c
        LEFT JOIN structure_nodes sn ON sn.id = c.structure_node_id
        WHERE c.embedding IS NOT NULL
              {scope}
        ORDER BY c.embedding <=> {vec_literal}
        LIMIT :limit
    """
    rows = await db.execute(sa_text(sql), params)
    hits = [
        _SearchHit(
            chunk_id=row[0],
            document_id=row[1],
            structure_node_id=row[2],
            page_number=row[3],
            heading_text=row[4],
            score=float(row[5]),
        )
        for row in rows.fetchall()
    ]
    update_current_observation(output={"hits": len(hits)})
    return hits


@observe(name="stage1_fulltext_search")
async def _fulltext_search(
    query: str,
    db: AsyncSession,
    *,
    document_id: uuid.UUID | None,
    document_ids: list[uuid.UUID] | None,
    space_id: uuid.UUID | None,
    top_k: int,
) -> list[_SearchHit]:
    """Lexical retrieval over chunk text plus heading-text matches."""

    q_or = _build_or_tsquery(query)
    if not q_or:
        update_current_observation(output={"hits": 0, "reason": "no_tokens"})
        return []

    params: dict = {"q_or": q_or, "limit": top_k}
    scope = _build_scope(params, document_id, document_ids, space_id)

    sql = f"""
        SELECT c.id, c.document_id, c.structure_node_id, c.page_number,
               sn.heading_text,
               GREATEST(
                   ts_rank_cd(c.tsv, to_tsquery('english', :q_or)),
                   ts_rank_cd(
                       to_tsvector('english', coalesce(sn.heading_text, '')),
                       to_tsquery('english', :q_or)
                   )
               ) AS rank,
               (
                   sn.heading_text IS NOT NULL
                   AND to_tsvector('english', sn.heading_text)
                       @@ to_tsquery('english', :q_or)
               ) AS heading_match
        FROM chunks c
        LEFT JOIN structure_nodes sn ON sn.id = c.structure_node_id
        WHERE (
                c.tsv @@ to_tsquery('english', :q_or)
                OR (
                    sn.heading_text IS NOT NULL
                    AND to_tsvector('english', sn.heading_text)
                        @@ to_tsquery('english', :q_or)
                )
              )
              {scope}
        ORDER BY rank DESC
        LIMIT :limit
    """
    rows = await db.execute(sa_text(sql), params)
    hits = [
        _SearchHit(
            chunk_id=row[0],
            document_id=row[1],
            structure_node_id=row[2],
            page_number=row[3],
            heading_text=row[4],
            score=float(row[5]),
            heading_match=bool(row[6]),
        )
        for row in rows.fetchall()
    ]
    update_current_observation(output={"hits": len(hits)})
    return hits


# ---------------------------------------------------------------------------
# RRF union + node aggregation + stats
# ---------------------------------------------------------------------------


@observe(name="stage1_build_candidates")
async def _build_candidates(
    sem_hits: list[_SearchHit],
    lex_hits: list[_SearchHit],
    context: ScopedContext,
    db: AsyncSession,
    *,
    top_k: int,
) -> tuple[list[ChunkCandidate], list[NodeCandidate], PrefetchStats]:
    """Fuse semantic + lexical hits with RRF, aggregate nodes, compute stats."""

    by_chunk: dict[str, ChunkCandidate] = {}

    for rank, hit in enumerate(sem_hits, start=1):
        cid = str(hit.chunk_id)
        cand = by_chunk.get(cid)
        if cand is None:
            cand = ChunkCandidate(
                chunk_id=cid,
                document_id=str(hit.document_id),
                structure_node_id=str(hit.structure_node_id) if hit.structure_node_id else None,
                page_number=hit.page_number,
                section_title=hit.heading_text,
            )
            by_chunk[cid] = cand
        cand.sem_score = max(cand.sem_score, hit.score)
        cand.sem_rank = min(cand.sem_rank, rank) if cand.sem_rank else rank

    for rank, hit in enumerate(lex_hits, start=1):
        cid = str(hit.chunk_id)
        cand = by_chunk.get(cid)
        if cand is None:
            cand = ChunkCandidate(
                chunk_id=cid,
                document_id=str(hit.document_id),
                structure_node_id=str(hit.structure_node_id) if hit.structure_node_id else None,
                page_number=hit.page_number,
                section_title=hit.heading_text,
            )
            by_chunk[cid] = cand
        cand.lex_score = max(cand.lex_score, hit.score)
        cand.lex_rank = min(cand.lex_rank, rank) if cand.lex_rank else rank
        cand.heading_match = cand.heading_match or hit.heading_match

    for cand in by_chunk.values():
        score = 0.0
        if cand.sem_rank is not None:
            score += 1.0 / (_RRF_K + cand.sem_rank)
        if cand.lex_rank is not None:
            score += 1.0 / (_RRF_K + cand.lex_rank)
        if cand.heading_match:
            score += _HEADING_MATCH_BOOST
        cand.fused_score = score

    chunk_candidates = sorted(by_chunk.values(), key=lambda c: c.fused_score, reverse=True)[:top_k]

    # Enrich chunk candidates with document titles in one query.
    doc_ids = {c.document_id for c in chunk_candidates if c.document_id}
    if doc_ids:
        rows = await db.execute(
            sa_text("SELECT id, title FROM documents WHERE id = ANY(:ids)"),
            {"ids": list(doc_ids)},
        )
        doc_titles = {str(r[0]): r[1] for r in rows.fetchall()}
        for cand in chunk_candidates:
            cand.document_title = doc_titles.get(cand.document_id)

    node_candidates = await _aggregate_nodes(chunk_candidates, db)
    stats = await _compute_stats(chunk_candidates, node_candidates, context, db)

    return chunk_candidates, node_candidates, stats


async def _aggregate_nodes(
    chunk_candidates: list[ChunkCandidate],
    db: AsyncSession,
) -> list[NodeCandidate]:
    """Group candidates by structure node and attach subtree metadata."""

    best_score: dict[str, float] = {}
    matched_count: dict[str, int] = {}
    doc_by_node: dict[str, str] = {}

    for cand in chunk_candidates:
        if not cand.structure_node_id:
            continue
        nid = cand.structure_node_id
        best_score[nid] = max(best_score.get(nid, 0.0), cand.fused_score)
        matched_count[nid] = matched_count.get(nid, 0) + 1
        doc_by_node.setdefault(nid, cand.document_id)

    if not best_score:
        return []

    rows = await db.execute(
        sa_text("""
            SELECT id, heading_text, heading_breadcrumb,
                   subtree_token_count, subtree_chunk_count
            FROM structure_nodes
            WHERE id = ANY(:ids)
        """),
        {"ids": list(best_score.keys())},
    )

    nodes: list[NodeCandidate] = []
    for row in rows.fetchall():
        nid = str(row[0])
        nodes.append(NodeCandidate(
            node_id=nid,
            document_id=doc_by_node.get(nid, ""),
            heading_text=row[1],
            heading_breadcrumb=row[2],
            best_score=best_score.get(nid, 0.0),
            matched_chunk_count=matched_count.get(nid, 0),
            subtree_token_count=int(row[3] or 0),
            subtree_chunk_count=int(row[4] or 0),
        ))

    nodes.sort(key=lambda n: n.best_score, reverse=True)
    return nodes


async def _compute_stats(
    chunk_candidates: list[ChunkCandidate],
    node_candidates: list[NodeCandidate],
    context: ScopedContext,
    db: AsyncSession,
) -> PrefetchStats:
    """Counts for the planner — cheap scope-aware SQL aggregates."""

    params: dict = {}
    scope = _build_scope(params, context.document_id, context.document_ids, context.space_id)

    chunk_row = await db.execute(
        sa_text(f"SELECT COUNT(*) FROM chunks c WHERE 1=1 {scope}"),
        params,
    )
    total_chunks = int(chunk_row.scalar() or 0)

    node_row = await db.execute(
        sa_text(f"""
            SELECT COUNT(*)
            FROM structure_nodes sn
            WHERE EXISTS (
                SELECT 1 FROM chunks c
                WHERE c.structure_node_id = sn.id
                {scope}
            )
        """),
        params,
    )
    total_nodes = int(node_row.scalar() or 0)

    if context.document_id:
        total_docs = 1
    elif context.document_ids:
        total_docs = len(context.document_ids)
    else:
        doc_row = await db.execute(
            sa_text("SELECT COUNT(*) FROM documents WHERE space_id = :space_id"),
            {"space_id": str(context.space_id)},
        )
        total_docs = int(doc_row.scalar() or 0)

    return PrefetchStats(
        total_doc_count=total_docs,
        total_chunk_count=total_chunks,
        total_structure_node_count=total_nodes,
        candidate_doc_count=len({c.document_id for c in chunk_candidates if c.document_id}),
        candidate_chunk_count=len(chunk_candidates),
        candidate_node_count=len(node_candidates),
    )


# ---------------------------------------------------------------------------
# Planner support context
# ---------------------------------------------------------------------------


async def _fetch_space_context(
    context: ScopedContext,
    db: AsyncSession,
) -> SpaceContext | None:
    """Fetch lightweight space context for the planner."""

    rows = await db.execute(
        sa_text("""
            SELECT d.id, d.title
            FROM documents d
            WHERE d.space_id = :space_id
            ORDER BY d.created_at
            LIMIT 50
        """),
        {"space_id": str(context.space_id)},
    )
    documents = [{"doc_id": str(row[0]), "title": row[1]} for row in rows.fetchall()]

    return SpaceContext(
        space_name=context.space_name,
        documents=documents,
        total_doc_count=len(documents),
    )


async def _fetch_last_turn(context: ScopedContext) -> dict[str, str] | None:
    """Placeholder — chat history still lives in the product backend."""

    if not context.session_id:
        return None
    return None
