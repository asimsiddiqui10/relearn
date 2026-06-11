"""Hybrid retrieval — pgvector semantic + tsv lexical, RRF fusion, heading boost.

Ported verbatim in spirit from reference/v1/stage1_prefetch.py (the hardest-won
retrieval logic), rewritten against the spec/02 schema and scoped to a run's
allowed documents. This is the `search_chunks` tool's internals.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_ai.llm import embed

logger = logging.getLogger(__name__)

_RRF_K = 60.0
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
# Additive boost when a chunk's section heading matches a query term. Calibrated
# (v1) so a single-source heading hit outranks a dual-source non-heading hit at
# mid-ranks — short queries keep their correct section.
_HEADING_MATCH_BOOST = 0.02


@dataclass
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    page_number: int | None
    heading_text: str | None
    score: float
    heading_match: bool = False


@dataclass
class FusedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    structure_node_id: uuid.UUID | None
    page_number: int | None
    section_title: str | None
    sem_rank: int | None = None
    lex_rank: int | None = None
    heading_match: bool = False
    fused_score: float = 0.0


def _or_tsquery(query: str) -> str:
    """OR-joined to_tsquery input. websearch_to_tsquery uses AND and silently
    returns nothing when one chunk lacks a term — the common RAG case. OR keeps
    any-term overlap as signal and lets RRF fuse it."""
    return " | ".join(_TOKEN_RE.findall(query))


def _scope_clause(params: dict, document_ids: list[uuid.UUID]) -> str:
    """Hard scope: restrict to the run's allowed documents. Empty list → match
    nothing (fail closed)."""
    params["doc_ids"] = [str(d) for d in document_ids] or ["00000000-0000-0000-0000-000000000000"]
    return "AND c.document_id = ANY(:doc_ids)"


async def _vector_search(
    query: str, db: AsyncSession, document_ids: list[uuid.UUID], top_k: int
) -> list[SearchHit]:
    try:
        vectors = await embed([query])
    except Exception as exc:
        logger.warning("embedding failed (%s) — skipping semantic search", exc)
        return []
    if not vectors or not vectors[0]:
        return []
    qv = vectors[0]
    if any(not math.isfinite(v) for v in qv) or all(v == 0.0 for v in qv):
        return []

    vec_literal = "'[" + ",".join(str(v) for v in qv) + "]'::vector"
    params: dict = {"limit": top_k}
    scope = _scope_clause(params, document_ids)
    sql = f"""
        SELECT c.id, c.document_id, c.structure_node_id, c.page_number, sn.heading_text,
               1 - (c.embedding <=> {vec_literal}) AS similarity
        FROM chunks c
        LEFT JOIN structure_nodes sn ON sn.id = c.structure_node_id
        WHERE c.embedding IS NOT NULL {scope}
        ORDER BY c.embedding <=> {vec_literal}
        LIMIT :limit
    """
    rows = (await db.execute(sa_text(sql), params)).fetchall()
    return [
        SearchHit(r[0], r[1], r[2], r[3], r[4], float(r[5])) for r in rows
    ]


async def _fulltext_search(
    query: str, db: AsyncSession, document_ids: list[uuid.UUID], top_k: int
) -> list[SearchHit]:
    q_or = _or_tsquery(query)
    if not q_or:
        return []
    params: dict = {"q_or": q_or, "limit": top_k}
    scope = _scope_clause(params, document_ids)
    sql = f"""
        SELECT c.id, c.document_id, c.structure_node_id, c.page_number, sn.heading_text,
               GREATEST(
                   ts_rank_cd(c.tsv, to_tsquery('english', :q_or)),
                   ts_rank_cd(to_tsvector('english', coalesce(sn.heading_text, '')),
                              to_tsquery('english', :q_or))
               ) AS rank,
               (sn.heading_text IS NOT NULL
                AND to_tsvector('english', sn.heading_text) @@ to_tsquery('english', :q_or)
               ) AS heading_match
        FROM chunks c
        LEFT JOIN structure_nodes sn ON sn.id = c.structure_node_id
        WHERE (
                c.tsv @@ to_tsquery('english', :q_or)
                OR (sn.heading_text IS NOT NULL
                    AND to_tsvector('english', sn.heading_text) @@ to_tsquery('english', :q_or))
              ) {scope}
        ORDER BY rank DESC
        LIMIT :limit
    """
    rows = (await db.execute(sa_text(sql), params)).fetchall()
    return [
        SearchHit(r[0], r[1], r[2], r[3], r[4], float(r[5]), bool(r[6])) for r in rows
    ]


def _fuse(sem: list[SearchHit], lex: list[SearchHit], top_k: int) -> list[FusedChunk]:
    by_chunk: dict[uuid.UUID, FusedChunk] = {}

    for rank, hit in enumerate(sem, start=1):
        c = by_chunk.setdefault(
            hit.chunk_id,
            FusedChunk(hit.chunk_id, hit.document_id, hit.structure_node_id,
                       hit.page_number, hit.heading_text),
        )
        c.sem_rank = rank if c.sem_rank is None else min(c.sem_rank, rank)

    for rank, hit in enumerate(lex, start=1):
        c = by_chunk.setdefault(
            hit.chunk_id,
            FusedChunk(hit.chunk_id, hit.document_id, hit.structure_node_id,
                       hit.page_number, hit.heading_text),
        )
        c.lex_rank = rank if c.lex_rank is None else min(c.lex_rank, rank)
        c.heading_match = c.heading_match or hit.heading_match

    for c in by_chunk.values():
        score = 0.0
        if c.sem_rank is not None:
            score += 1.0 / (_RRF_K + c.sem_rank)
        if c.lex_rank is not None:
            score += 1.0 / (_RRF_K + c.lex_rank)
        if c.heading_match:
            score += _HEADING_MATCH_BOOST
        c.fused_score = score

    return sorted(by_chunk.values(), key=lambda c: c.fused_score, reverse=True)[:top_k]


async def hybrid_search(
    query: str, db: AsyncSession, document_ids: list[uuid.UUID], *, top_k: int = 12
) -> list[FusedChunk]:
    """Run semantic + lexical retrieval in the run's scope and RRF-fuse them."""
    sem = await _vector_search(query, db, document_ids, top_k)
    lex = await _fulltext_search(query, db, document_ids, top_k)
    return _fuse(sem, lex, top_k)
