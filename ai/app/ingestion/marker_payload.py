"""Unwrap Marker API envelopes vs raw document JSON trees (ported from v1)."""

from __future__ import annotations

from typing import Any

# Bump when mapping logic changes (stored on marker_ingest_runs for reprocessing).
MARKER_INGEST_PARSER_VERSION = "4"  # v4 (Phase 0): new schema — coarse chunk_type,
#                                     ordinal structure_path, figure_ref_norm on images


def normalize_marker_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return (document_root, envelope).

    Hosted APIs wrap the tree as {"success", "filename", "json": {...}, ...};
    local/CLI output may be the document object directly.
    """
    if not isinstance(payload, dict):
        raise TypeError("marker payload must be a dict")

    inner = payload.get("json")
    if isinstance(inner, dict) and (
        inner.get("block_type") == "Document"
        or "children" in inner
        or inner.get("metadata") is not None
    ):
        envelope = {k: v for k, v in payload.items() if k != "json"}
        return inner, envelope

    if "children" in payload or payload.get("block_type") == "Document":
        return payload, None

    raise ValueError(
        "Unrecognized Marker payload shape: expected top-level 'json' document "
        "or Document-shaped dict"
    )


def document_metadata_for_db(document_root: dict[str, Any]) -> dict[str, Any] | None:
    """Marker document metadata (table_of_contents, page_stats) for documents.metadata_json."""
    meta = document_root.get("metadata")
    return meta if isinstance(meta, dict) else None
