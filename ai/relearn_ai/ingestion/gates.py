"""Quality gates before commit (spec/05, v1 set).

Gate failure → repair attempt → re-gate → still failing → resource marked
`failed` with a human-readable reason. Never silently commit garbage.
"""

from __future__ import annotations

from dataclasses import dataclass

from relearn_ai.ingestion.tree_mapper import MappedDocument

# thresholds (v1-calibrated)
MIN_NONEMPTY_TEXT_RATIO = 0.3  # below → likely scanned/encoded PDF
MAX_DEPTH_JUMP = 1  # parent.depth -> child.depth must increase by exactly 1
MAX_GIANT_CHUNK_TOKENS = 4000  # single chunk this large → table-explosion artifact
MAX_GIANT_CHUNK_RATIO = 0.05


@dataclass
class GateResult:
    passed: bool
    failures: list[str]


def run_quality_gates(mapped: MappedDocument, page_count: int) -> GateResult:
    failures: list[str] = []

    # 1. zero-chunk document
    if not mapped.chunks:
        failures.append("no chunks extracted — document parsed to nothing")
        return GateResult(False, failures)

    # 2. non-empty text ratio per page
    if page_count > 0:
        pages_with_text = {
            c.page_number for c in mapped.chunks if c.content.strip() and c.page_number is not None
        }
        ratio = len(pages_with_text) / page_count
        if ratio < MIN_NONEMPTY_TEXT_RATIO:
            failures.append(
                f"only {len(pages_with_text)}/{page_count} pages have text "
                f"(ratio {ratio:.2f} < {MIN_NONEMPTY_TEXT_RATIO}) — "
                "likely a scanned or font-encoded PDF; OCR path needed"
            )

    # 3. heading tree sanity — orphan depth jumps
    node_by_id = {n.id: n for n in mapped.structure_nodes}
    for n in mapped.structure_nodes:
        if n.parent_node_id is None:
            continue
        parent = node_by_id.get(n.parent_node_id)
        if parent is None:
            failures.append(f"structure node {n.heading_text!r} has unknown parent")
        elif n.depth - parent.depth != 1:
            failures.append(
                f"depth jump at {n.heading_text!r}: parent depth {parent.depth} "
                f"-> child depth {n.depth}"
            )

    # 4. chunk length distribution — table-explosion artifacts
    giant = [c for c in mapped.chunks if c.token_count > MAX_GIANT_CHUNK_TOKENS]
    if len(giant) / len(mapped.chunks) > MAX_GIANT_CHUNK_RATIO:
        failures.append(
            f"{len(giant)}/{len(mapped.chunks)} chunks exceed {MAX_GIANT_CHUNK_TOKENS} tokens "
            "— chunk-size distribution looks broken (table explosion?)"
        )

    return GateResult(not failures, failures)
